"""Atomic control projection and one-writer operating lock."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from typing import Any, Mapping
import os
import tempfile

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


class ControlStateError(RuntimeError):
    """The control projection is invalid or failed a CAS boundary."""


class ConcurrentWriterError(ControlStateError):
    """Another writer owns the operating lock."""


_THREAD_LOCKS_GUARD = Lock()
_THREAD_LOCKS: dict[str, Lock] = {}


def _thread_lock(path: Path) -> Lock:
    key = str(path.resolve()).casefold()
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, Lock())


class WriterLock(AbstractContextManager["WriterLock"]):
    """Dedicated byte-range lock that survives control-file replacement."""

    def __init__(self, path: str | Path, *, timeout_seconds: int = 5) -> None:
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds
        self._handle: Any = None
        self._thread_lock = _thread_lock(self.path)

    def __enter__(self) -> "WriterLock":
        if not self._thread_lock.acquire(timeout=self.timeout_seconds):
            raise ConcurrentWriterError("writer thread lock is busy")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a+b")
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                self._handle.write(b"\0")
                self._handle.flush()
            deadline = monotonic() + self.timeout_seconds
            while True:
                try:
                    self._lock_byte()
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
    if control.get("schema") != "axiom_control":
        raise ControlStateError("unexpected control schema")
    revision = control.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ControlStateError("control revision is invalid")
    if control.get("control_hash") != control_hash(control):
        raise ControlStateError("control hash mismatch")
    authority = control.get("authority")
    engineering = control.get("engineering")
    scientific = control.get("scientific")
    next_action = control.get("next_action")
    if not isinstance(authority, dict) or authority.get("graph_count") != 1:
        raise ControlStateError("control must bind one authority graph")
    if (
        not isinstance(engineering, dict)
        or engineering.get("mutable_control_state_count") != 1
    ):
        raise ControlStateError("control must bind one mutable state")
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
    if not isinstance(next_action, dict) or not isinstance(next_action.get("kind"), str):
        raise ControlStateError("one structured next action is required")
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
        isinstance(journal_sequence, bool)
        or not isinstance(journal_sequence, int)
        or journal_sequence < 1
        or journal_sequence != revision
        or index_sequence != journal_sequence
        or isinstance(index_record_count, bool)
        or not isinstance(index_record_count, int)
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
    ):
        raise ControlStateError("a future holdout requirement needs an active Mission")
    if scientific.get("active_initiative") is not None and scientific.get("active_mission") is None:
        raise ControlStateError("an Initiative requires an active Mission")
    if scientific.get("active_study") is not None and scientific.get("active_initiative") is None:
        raise ControlStateError("a Study requires an active Initiative")
    if scientific.get("active_batch") is not None and scientific.get("active_study") is None:
        raise ControlStateError("a Batch requires an active Study")
    active_job = scientific.get("active_job")
    active_repair = scientific.get("active_repair")
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
    if isinstance(active_job, dict):
        allowed_next = {
            "declared": {"issue_job_permit"},
            "running": {"resume_job", "evaluate_frozen_holdout"},
            "interrupted_repair": {"execute_repair"},
        }[active_job["status"]]
        if next_action.get("kind") not in allowed_next:
            raise ControlStateError("active Job and next action are incoherent")
    if next_action.get("kind") == "close_mission" and (
        next_action.get("outcome")
        not in {"completed_pre_live_handoff", "closed_no_candidate", "blocked_external"}
        or not isinstance(next_action.get("basis_record_id"), str)
    ):
        raise ControlStateError("pending terminal action is malformed")
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
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        value = parse_canonical(self.path.read_bytes())
        if not isinstance(value, dict):
            raise ControlStateError("control document must be an object")
        validate_control(value)
        return dict(value)

    def replace(self, control: Mapping[str, Any]) -> dict[str, Any]:
        sealed = seal_control(control)
        payload = canonical_bytes(sealed)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            observed = self.read()
            if observed != sealed:
                raise ControlStateError("post-replace control verification failed")
            return sealed
        finally:
            if temporary.exists():
                temporary.unlink()

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
