"""Atomic control projection and one-writer operating lock."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from typing import Any, Mapping
import os
import stat

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.atomic_file import (
    AtomicFileError,
    replace_stable_regular_file,
)
from axiom_rift.storage.control_next_action import (
    ControlNextActionError,
    is_successor_mission_boundary,
    validate_control_next_action,
)
from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    ensure_link_free_directory_chain,
    read_stable_regular_file,
    require_link_free_directory_chain,
)


class ControlStateError(RuntimeError):
    """The control projection is invalid or failed a CAS boundary."""


class ConcurrentWriterError(ControlStateError):
    """Another writer owns the operating lock."""


_THREAD_LOCKS_GUARD = Lock()
_THREAD_LOCKS: dict[str, Lock] = {}
_MAX_CONTROL_BYTES = 1_048_576


def _is_ascii_text(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_prefixed_digest(value: Any, prefix: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(prefix)
        and _is_digest(value.removeprefix(prefix))
    )


def _thread_lock(path: Path) -> Lock:
    key = str(path.resolve()).casefold()
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, Lock())


def _link_like(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _require_same_lock_file(path: Path, descriptor: int) -> None:
    try:
        path_metadata = path.lstat()
        open_metadata = os.fstat(descriptor)
    except OSError as exc:
        raise ControlStateError("writer lock file identity is unavailable") from exc
    if (
        _link_like(path_metadata)
        or not stat.S_ISREG(path_metadata.st_mode)
        or path_metadata.st_nlink != 1
        or (path_metadata.st_dev, path_metadata.st_ino)
        != (open_metadata.st_dev, open_metadata.st_ino)
    ):
        raise ControlStateError("writer lock file is link-like or changed identity")


class WriterLock(AbstractContextManager["WriterLock"]):
    """Dedicated byte-range lock that survives control-file replacement."""

    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: int = 5,
        create_if_missing: bool = True,
    ) -> None:
        if (
            type(timeout_seconds) is not int
            or timeout_seconds <= 0
        ):
            raise ValueError("writer lock timeout_seconds must be a positive integer")
        if type(create_if_missing) is not bool:
            raise ValueError("writer lock create_if_missing must be boolean")
        self.path = Path(os.path.abspath(path))
        self.timeout_seconds = timeout_seconds
        self.create_if_missing = create_if_missing
        self._handle: Any = None
        self._thread_lock = _thread_lock(self.path)

    def __enter__(self) -> "WriterLock":
        if not self._thread_lock.acquire(timeout=self.timeout_seconds):
            raise ConcurrentWriterError("writer thread lock is busy")
        try:
            try:
                if self.create_if_missing:
                    ensure_link_free_directory_chain(self.path.parent)
                else:
                    require_link_free_directory_chain(self.path.parent)
            except (OSError, PathBoundaryError) as exc:
                raise ControlStateError(
                    "writer lock directory is unavailable"
                ) from exc
            try:
                if self.create_if_missing:
                    try:
                        self._handle = self.path.open("x+b")
                    except FileExistsError:
                        metadata = self.path.lstat()
                        if (
                            _link_like(metadata)
                            or not stat.S_ISREG(metadata.st_mode)
                            or metadata.st_nlink != 1
                        ):
                            raise ControlStateError(
                                "writer lock file is link-like or invalid"
                            )
                        self._handle = self.path.open("r+b")
                else:
                    self._handle = self.path.open("r+b")
            except ControlStateError:
                raise
            except OSError as exc:
                raise ControlStateError(
                    "existing writer lock is unavailable"
                ) from exc
            try:
                require_link_free_directory_chain(self.path.parent)
            except PathBoundaryError as exc:
                raise ControlStateError(
                    "writer lock directory changed during open"
                ) from exc
            _require_same_lock_file(self.path, self._handle.fileno())
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                if not self.create_if_missing:
                    raise ControlStateError(
                        "existing writer lock is empty"
                    )
                self._handle.write(b"\0")
                self._handle.flush()
            self._handle.seek(0)
            if self._handle.read(2) != b"\0":
                raise ControlStateError(
                    "writer lock must contain exactly one sentinel byte"
                )
            deadline = monotonic() + self.timeout_seconds
            while True:
                try:
                    self._lock_byte()
                    _require_same_lock_file(self.path, self._handle.fileno())
                    break
                except OSError as exc:
                    if monotonic() >= deadline:
                        raise ConcurrentWriterError("writer process lock is busy") from exc
                    sleep(0.05)
            return self
        except BaseException:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            self._thread_lock.release()
            raise

    def _lock_byte(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_byte(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)

    def __exit__(self, *_exc_info: object) -> None:
        try:
            if self._handle is not None:
                self._unlock_byte()
                self._handle.close()
                self._handle = None
        finally:
            self._thread_lock.release()


def control_hash(control: Mapping[str, Any]) -> str:
    body = dict(control)
    body.pop("control_hash", None)
    return canonical_digest(domain="control", payload=body)


def validate_control(control: Mapping[str, Any]) -> None:
    expected_control_keys = {
        "authority",
        "authorizations",
        "control_hash",
        "engineering",
        "heads",
        "initiative",
        "next_action",
        "revision",
        "schema",
        "scientific",
    }
    if set(control) != expected_control_keys:
        raise ControlStateError("control top-level surface is not exact")
    if control.get("schema") != "axiom_control":
        raise ControlStateError("unexpected control schema")
    revision = control.get("revision")
    if type(revision) is not int or revision < 0:
        raise ControlStateError("control revision is invalid")
    if control.get("control_hash") != control_hash(control):
        raise ControlStateError("control hash mismatch")
    authority = control.get("authority")
    engineering = control.get("engineering")
    scientific = control.get("scientific")
    next_action = control.get("next_action")
    expected_authority_keys = {
        "contracts",
        "foundation_inputs",
        "graph_count",
        "manifest_digest",
        "operating_direction",
    }
    if (
        not isinstance(authority, dict)
        or set(authority) != expected_authority_keys
        or type(authority.get("graph_count")) is not int
        or authority.get("graph_count") != 1
    ):
        raise ControlStateError("control must bind one authority graph")
    contracts = authority.get("contracts")
    foundation_inputs = authority.get("foundation_inputs")
    operating_direction = authority.get("operating_direction")
    manifest_digest = authority.get("manifest_digest")
    if (
        not isinstance(contracts, list)
        or not contracts
        or not isinstance(foundation_inputs, list)
        or not foundation_inputs
        or not isinstance(operating_direction, str)
        or not operating_direction
        or not isinstance(manifest_digest, str)
        or len(manifest_digest) != 64
        or any(character not in "0123456789abcdef" for character in manifest_digest)
    ):
        raise ControlStateError("authority manifest shape is invalid")
    authority_paths = [operating_direction, *contracts, *foundation_inputs]
    if (
        any(not _is_ascii_text(value) for value in authority_paths)
        or len(set(authority_paths)) != len(authority_paths)
        or any(
            Path(value).is_absolute()
            or value in {".", "./"}
            or ".." in Path(value).parts
            for value in authority_paths
        )
    ):
        raise ControlStateError("authority paths are invalid")
    base_engineering_keys = {
        "active_authority_graph_count",
        "harness_status",
        "mutable_control_state_count",
    }
    if not isinstance(engineering, dict) or frozenset(engineering) not in {
        frozenset(base_engineering_keys),
        frozenset({*base_engineering_keys, "commissioning_fixture"}),
    }:
        raise ControlStateError("engineering control surface is not exact")
    if (
        engineering.get("harness_status") != "ready"
        or type(engineering.get("active_authority_graph_count")) is not int
        or engineering.get("active_authority_graph_count") != 1
        or type(engineering.get("mutable_control_state_count")) is not int
        or engineering.get("mutable_control_state_count") != 1
        or (
            "commissioning_fixture" in engineering
            and engineering.get("commissioning_fixture") is not True
        )
    ):
        raise ControlStateError("control must bind one mutable state")
    initiative = control.get("initiative")
    if initiative != {
        "id": "INI-0001",
        "outcome": "completed_ready_boundary",
        "status": "closed",
    }:
        raise ControlStateError("Foundation initiative projection is invalid")
    if not isinstance(scientific, dict):
        raise ControlStateError("scientific projection is missing")
    expected_scientific_keys = {
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
        "required_future_holdout_id",
        "holdout_reveals",
        "claim",
    }
    if set(scientific) != expected_scientific_keys:
        raise ControlStateError("scientific control surface is not exact")
    for identity_key in ("active_mission", "active_initiative", "active_study"):
        identity = scientific.get(identity_key)
        if identity is not None and not _is_ascii_text(identity):
            raise ControlStateError(f"{identity_key} identity is invalid")
    active_executable_id = scientific.get("active_executable")
    if active_executable_id is not None and not _is_prefixed_digest(
        active_executable_id, "executable:"
    ):
        raise ControlStateError("active_executable identity is invalid")
    if scientific.get("active_lineage") is not None:
        raise ControlStateError("active_lineage has no mutable control projection")
    required_holdout_id = scientific.get("required_future_holdout_id")
    if required_holdout_id is not None and not _is_prefixed_digest(
        required_holdout_id, "holdout:"
    ):
        raise ControlStateError("required future holdout identity is invalid")
    holdout_reveals = scientific.get("holdout_reveals")
    if type(holdout_reveals) is not int or holdout_reveals < 0:
        raise ControlStateError("holdout reveal count is invalid")
    if scientific.get("claim") != "none":
        raise ControlStateError("control cannot carry scientific claim authority")

    active_batch = scientific.get("active_batch")
    if active_batch is not None and (
        not isinstance(active_batch, dict)
        or set(active_batch) != {"hash", "id", "status"}
        or not _is_prefixed_digest(active_batch.get("id"), "batch:")
        or not _is_digest(active_batch.get("hash"))
        or active_batch.get("id") != f"batch:{active_batch.get('hash')}"
        or active_batch.get("status") != "open"
    ):
        raise ControlStateError("active Batch projection is invalid")

    active_job = scientific.get("active_job")
    active_job_required_keys = {"hash", "id", "resume_action", "status"}
    active_job_optional_keys = {
        "engine_entry_record_id",
        "last_repair_resume_record_id",
        "required_engineering_disposition_hash",
        "required_engineering_failure_cause_hash",
        "required_engineering_repair_id",
        "required_repair_resume_record_id",
        "return_next_action",
        "runtime_entry_record_id",
        "start_record_id",
    }
    if active_job is not None:
        if (
            not isinstance(active_job, dict)
            or not active_job_required_keys.issubset(active_job)
            or set(active_job).difference(
                active_job_required_keys | active_job_optional_keys
            )
            or not _is_prefixed_digest(active_job.get("id"), "job:")
            or not _is_digest(active_job.get("hash"))
            or active_job.get("id") != f"job:{active_job.get('hash')}"
            or not _is_ascii_text(active_job.get("resume_action"))
            or active_job.get("status")
            not in {"declared", "running", "interrupted_repair"}
        ):
            raise ControlStateError("active Job projection is invalid")
        return_next_action = active_job.get("return_next_action")
        if "return_next_action" in active_job and (
            not isinstance(return_next_action, dict)
            or not _is_ascii_text(return_next_action.get("kind"))
        ):
            raise ControlStateError("active Job return action is invalid")
        for digest_key in (
            "engine_entry_record_id",
            "last_repair_resume_record_id",
            "required_engineering_disposition_hash",
            "required_engineering_failure_cause_hash",
            "required_repair_resume_record_id",
            "runtime_entry_record_id",
            "start_record_id",
        ):
            if digest_key in active_job and not _is_digest(active_job[digest_key]):
                raise ControlStateError("active Job provenance is invalid")
        engineering_disposition_keys = {
            "required_engineering_disposition_hash",
            "required_engineering_failure_cause_hash",
            "required_engineering_repair_id",
        }
        present_disposition_keys = engineering_disposition_keys.intersection(
            active_job
        )
        repair_id = active_job.get("required_engineering_repair_id")
        if (
            present_disposition_keys not in (set(), engineering_disposition_keys)
            or (
                repair_id is not None
                and not _is_prefixed_digest(repair_id, "repair:")
            )
            or (
                "engine_entry_record_id" in active_job
                and "runtime_entry_record_id" in active_job
            )
            or (
                active_job.get("status") == "declared"
                and any(
                    key in active_job
                    for key in (
                        "engine_entry_record_id",
                        "required_repair_resume_record_id",
                        "runtime_entry_record_id",
                        "start_record_id",
                    )
                )
            )
            or (
                active_job.get("status") in {"running", "interrupted_repair"}
                and "start_record_id" not in active_job
            )
        ):
            raise ControlStateError("active Job state is incoherent")

    active_release = scientific.get("active_release")
    if active_release is not None and (
        not isinstance(active_release, dict)
        or set(active_release)
        != {"candidate_id", "executable_id", "id", "status"}
        or not _is_ascii_text(active_release.get("id"))
        or not _is_prefixed_digest(
            active_release.get("candidate_id"), "candidate:"
        )
        or not _is_prefixed_digest(
            active_release.get("executable_id"), "executable:"
        )
        or active_release.get("status") not in {"declared", "frozen"}
        or active_release.get("executable_id")
        != scientific.get("active_executable")
    ):
        raise ControlStateError("active Release projection is invalid")
    if not isinstance(next_action, dict):
        raise ControlStateError("one structured next action is required")
    successor_boundary = is_successor_mission_boundary(next_action)
    heads = control.get("heads")
    if not isinstance(heads, dict) or set(heads) != {"journal", "index"}:
        raise ControlStateError("control must bind exact journal and index heads")
    journal_head = heads.get("journal")
    index_head = heads.get("index")
    if not isinstance(journal_head, dict) or set(journal_head) != {
        "sequence",
        "event_id",
    }:
        raise ControlStateError("journal head is invalid")
    if not isinstance(index_head, dict) or set(index_head) != {
        "required_sequence",
        "required_record_count",
        "required_projection_digest",
    }:
        raise ControlStateError("index head is invalid")
    journal_sequence = journal_head.get("sequence")
    index_sequence = index_head.get("required_sequence")
    index_record_count = index_head.get("required_record_count")
    index_projection_digest = index_head.get("required_projection_digest")
    event_id = journal_head.get("event_id")
    if (
        type(journal_sequence) is not int
        or journal_sequence < 1
        or journal_sequence != revision
        or type(index_sequence) is not int
        or index_sequence != journal_sequence
        or type(index_record_count) is not int
        or index_record_count < 1
        or not isinstance(index_projection_digest, str)
        or len(index_projection_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in index_projection_digest
        )
        or not isinstance(event_id, str)
        or len(event_id) != 64
        or any(character not in "0123456789abcdef" for character in event_id)
    ):
        raise ControlStateError("control heads do not match the committed revision")
    if scientific.get("active_job") is not None and scientific.get("active_mission") is None:
        raise ControlStateError("a Job requires an active Mission")
    if scientific.get("active_repair") is not None and scientific.get("active_job") is None:
        raise ControlStateError("a Repair requires an interrupted Job")
    if scientific.get("active_release") is not None and (
        scientific.get("active_mission") is None
        or scientific.get("active_executable") is None
    ):
        raise ControlStateError("an active Release requires its Mission and Executable")
    if scientific.get("active_holdout_evaluation") is not None and (
        scientific.get("active_mission") is None
        or scientific.get("active_executable") is None
    ):
        raise ControlStateError("an active holdout requires its Mission and Executable")
    if (
        scientific.get("required_future_holdout_id") is not None
        and scientific.get("active_mission") is None
        and not successor_boundary
        and next_action.get("kind") != "await_external_change"
    ):
        raise ControlStateError("a future holdout requirement needs an active Mission")
    if scientific.get("active_initiative") is not None and scientific.get("active_mission") is None:
        raise ControlStateError("an Initiative requires an active Mission")
    disposed_boundary = next_action.get("kind") in {
        "await_root_goal",
        "await_external_change",
        "project_goal_complete",
    }
    if disposed_boundary and any(
        scientific.get(name) is not None
        for name in expected_scientific_keys
        if name.startswith("active_")
    ):
        raise ControlStateError("a disposed Mission boundary retains active work")
    if scientific.get("active_study") is not None and scientific.get("active_initiative") is None:
        raise ControlStateError("a Study requires an active Initiative")
    if scientific.get("active_batch") is not None and scientific.get("active_study") is None:
        raise ControlStateError("a Batch requires an active Study")
    active_job = scientific.get("active_job")
    active_repair = scientific.get("active_repair")
    active_holdout = scientific.get("active_holdout_evaluation")
    if active_holdout is not None:
        if not isinstance(active_holdout, dict):
            raise ControlStateError("active holdout projection is invalid")
        holdout_status = active_holdout.get("status")
        base_holdout_keys = {
            "candidate_id",
            "executable_id",
            "holdout_id",
            "job_id",
            "status",
        }
        if (
            not base_holdout_keys.issubset(active_holdout)
            or not _is_prefixed_digest(
                active_holdout.get("candidate_id"), "candidate:"
            )
            or not _is_prefixed_digest(
                active_holdout.get("executable_id"), "executable:"
            )
            or not _is_prefixed_digest(
                active_holdout.get("holdout_id"), "holdout:"
            )
            or not _is_prefixed_digest(active_holdout.get("job_id"), "job:")
            or active_holdout.get("executable_id")
            != scientific.get("active_executable")
        ):
            raise ControlStateError("active holdout identity is invalid")
        if holdout_status == "revealed_pending_evaluation":
            if (
                set(active_holdout) != base_holdout_keys
                or not isinstance(active_job, dict)
                or active_job.get("id") != active_holdout.get("job_id")
                or active_job.get("status") != "running"
            ):
                raise ControlStateError(
                    "revealed holdout must retain its active Job"
                )
        elif holdout_status in {
            "evaluation_completed_pending_disposition",
            "engineering_gap_pending_disposition",
        }:
            completion_id = active_holdout.get("completion_record_id")
            if (
                set(active_holdout)
                != {*base_holdout_keys, "completion_record_id"}
                or active_job is not None
                or not _is_digest(completion_id)
            ):
                raise ControlStateError(
                    "completed holdout lacks its exact pending disposition"
                )
        else:
            raise ControlStateError("active holdout status is invalid")
    if active_job is not None:
        if not isinstance(active_job, dict) or active_job.get("status") not in {
            "declared",
            "running",
            "interrupted_repair",
        }:
            raise ControlStateError("active Job status is invalid")
        if (active_job.get("status") == "interrupted_repair") != (
            active_repair is not None
        ):
            raise ControlStateError("Job and Repair status are incoherent")
    if active_repair is not None:
        if not isinstance(active_repair, dict):
            raise ControlStateError("active Repair projection is invalid")
        expected_repair_keys = {
            "cause_hash",
            "episode",
            "id",
            "job_id",
            "latest_attempt_record_id",
            "latest_basis_hash",
            "predecessor_repair_close_record_id",
            "resume_action",
        }
        repair_id = active_repair.get("id")
        predecessor_id = active_repair.get(
            "predecessor_repair_close_record_id"
        )
        latest_attempt_id = active_repair.get("latest_attempt_record_id")
        episode = active_repair.get("episode")
        if (
            set(active_repair) != expected_repair_keys
            or not isinstance(repair_id, str)
            or not repair_id.startswith("repair:")
            or not _is_digest(repair_id.removeprefix("repair:"))
            or not isinstance(active_job, dict)
            or active_repair.get("job_id") != active_job.get("id")
            or not _is_digest(active_repair.get("cause_hash"))
            or not _is_digest(active_repair.get("latest_basis_hash"))
            or type(episode) is not int
            or episode < 1
            or not _is_ascii_text(active_repair.get("resume_action"))
            or (
                predecessor_id is not None
                and not _is_digest(predecessor_id)
            )
            or (episode == 1) != (predecessor_id is None)
            or (
                latest_attempt_id is not None
                and not _is_digest(latest_attempt_id)
            )
            or (
                latest_attempt_id is None
                and active_repair.get("latest_basis_hash")
                != active_repair.get("cause_hash")
            )
            or repair_id
            != "repair:"
            + canonical_digest(
                domain="repair",
                payload={
                    "cause_hash": active_repair.get("cause_hash"),
                    "episode": episode,
                    "job_id": active_repair.get("job_id"),
                    "predecessor_repair_close_record_id": predecessor_id,
                },
            )
        ):
            raise ControlStateError("active Repair projection is invalid")
    try:
        validate_control_next_action(
            next_action,
            scientific,
            engineering_fixture=(
                engineering.get("commissioning_fixture") is True
            ),
        )
    except ControlNextActionError as exc:
        raise ControlStateError(str(exc)) from exc
    expected_authorizations: set[str] = set()
    for key, label in (
        ("active_mission", "Mission"),
        ("active_initiative", "Initiative"),
        ("active_study", "Study"),
        ("active_executable", "Executable"),
    ):
        value = scientific.get(key)
        if value is not None:
            expected_authorizations.add(f"{label}:{value}")
    if isinstance(active_job, dict):
        expected_authorizations.add(f"Job:{active_job.get('id')}")
    release = scientific.get("active_release")
    if isinstance(release, dict) and release.get("status") == "declared":
        expected_authorizations.add(f"Release:{release.get('id')}")
    authorizations = control.get("authorizations")
    if not isinstance(authorizations, dict) or set(authorizations) != expected_authorizations:
        raise ControlStateError("active subject authorizations are not exact")
    expected_authorization_payload_keys = {
        "authorization_epoch",
        "authorization_hash",
        "kind",
        "subject_id",
    }
    for authorization_key, authorization in authorizations.items():
        kind, subject_id = authorization_key.split(":", 1)
        if (
            not isinstance(authorization, dict)
            or set(authorization) != expected_authorization_payload_keys
            or authorization.get("kind") != kind
            or authorization.get("subject_id") != subject_id
            or kind not in {"Executable", "Initiative", "Job", "Mission", "Release", "Study"}
            or not _is_ascii_text(subject_id)
            or type(authorization.get("authorization_epoch")) is not int
            or authorization["authorization_epoch"] < 1
            or not _is_digest(authorization.get("authorization_hash"))
        ):
            raise ControlStateError("active subject authorization payload is invalid")
        if kind == "Job":
            if not isinstance(active_job, dict):
                raise ControlStateError("Job authorization has no active Job")
            expected_job_authorization = canonical_digest(
                domain="subject-authorization",
                payload={
                    "epoch": authorization["authorization_epoch"],
                    "kind": "Job",
                    "semantic_hash": active_job["hash"],
                    "subject_id": subject_id,
                },
            )
            if authorization["authorization_hash"] != expected_job_authorization:
                raise ControlStateError(
                    "active Job authorization hash is not self-consistent"
                )
    for historical_key in (
        "portfolio_history",
        "historical_objects",
        "evidence_catalog",
        "study_history",
        "job_history",
        "trial_references",
        "negative_memory",
        "candidates",
        "releases",
        "external_sources",
        "source_permits",
        "holdout_permits",
        "runtime_permits",
    ):
        if historical_key in scientific:
            raise ControlStateError(f"historical array forbidden in control: {historical_key}")


def seal_control(control: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(control)
    value.pop("control_hash", None)
    value["control_hash"] = control_hash(value)
    validate_control(value)
    return value


class ControlStore:
    """Read and atomically replace the sole mutable control projection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, Any] | None:
        try:
            payload = read_stable_regular_file(
                self.path,
                max_bytes=_MAX_CONTROL_BYTES,
                missing_ok=True,
            )
        except PathBoundaryError as exc:
            raise ControlStateError(
                "control file changed or became unavailable while read: "
                f"{exc}"
            ) from exc
        if payload is None:
            return None
        value = parse_canonical(payload)
        if not isinstance(value, dict):
            raise ControlStateError("control document must be an object")
        validate_control(value)
        return dict(value)

    def replace(self, control: Mapping[str, Any]) -> dict[str, Any]:
        sealed = seal_control(control)
        payload = canonical_bytes(sealed)
        try:
            replace_stable_regular_file(self.path, payload)
        except AtomicFileError as exc:
            raise ControlStateError(
                "control atomic replacement boundary is invalid: "
                f"{exc}"
            ) from exc
        observed = self.read()
        if observed != sealed:
            raise ControlStateError("post-replace control verification failed")
        return sealed

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        expected_event_id: str | None,
        replacement: Mapping[str, Any],
    ) -> dict[str, Any]:
        current = self.read()
        current_revision = -1 if current is None else current["revision"]
        current_event = (
            None if current is None else current["heads"]["journal"]["event_id"]
        )
        if current_revision != expected_revision or current_event != expected_event_id:
            raise ControlStateError("control compare-and-swap mismatch")
        return self.replace(replacement)
