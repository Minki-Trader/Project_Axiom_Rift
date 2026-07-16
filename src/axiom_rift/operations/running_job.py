"""Read-only authority boundary for one running Job execution.

The state writer owns mutations.  Engines need a much smaller surface: they
must reconstruct an already-started Job capability and, for reproducible
caches, rejoin the exact completed producer.  Keeping that verification here
prevents unrelated lifecycle policy in ``operations.writer`` from changing a
scientific implementation identity while preserving the same Journal, control,
permit, index, and evidence-scope checks at the engine boundary.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any
import os

import axiom_rift.core.canonical as canonical_module
import axiom_rift.core.identity as identity_module
import axiom_rift.operations.completion_evidence_scope as completion_scope_module
import axiom_rift.operations.permits as permits_module
import axiom_rift.operations.repair_semantic_equivalence as repair_semantic_module
import axiom_rift.research.effective_evidence_scope as effective_scope_module
import axiom_rift.storage.index as index_module
import axiom_rift.storage.journal as journal_module
import axiom_rift.storage.path_boundary as path_boundary_module
import axiom_rift.storage.state as state_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.completion_evidence_scope import (
    CompletionEvidenceScopeError,
    current_study_cache_evidence_scope,
)
from axiom_rift.operations.permits import (
    Permit,
    PermitError,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.repair_semantic_equivalence import (
    RepairSemanticEquivalenceError,
    require_passed_semantic_equivalence_facts,
)
from axiom_rift.storage.index import (
    IndexIntegrityError,
    IndexRecord,
    LocalIndex,
    LocalIndexError,
    LocalIndexView,
)
from axiom_rift.storage.journal import DurableJournal, LEGACY_JOURNAL_RELATIVE_PATH
from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    read_stable_regular_file,
)
from axiom_rift.storage.state import (
    ControlStateError,
    ControlStore,
    WriterLock,
    seal_control,
)


_AUTHORITATIVE_EVENT_CACHE_SIZE = 64
_THIS_FILE = Path(__file__).resolve()


class RunningJobAuthorityError(RuntimeError):
    """A read-only running-Job authority projection is malformed."""


class RunningJobAuthorityIntegrityError(RunningJobAuthorityError):
    """Control, Journal, index, or effective-scope authority diverged."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _authority_integer(name: str, value: object, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise RunningJobAuthorityIntegrityError(
            f"{name} must be an integer >= {minimum}"
        )
    return value


def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = parse_canonical(canonical_bytes(dict(value)))
    if not isinstance(copied, dict):
        raise RunningJobAuthorityIntegrityError(
            "canonical authority mapping is not an object"
        )
    return dict(copied)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunningJobExecution:
    """Immutable identity of one writer-authorized running Job execution."""

    job_id: str
    job_hash: str
    start_record_id: str
    job_permit_id: str

    def __post_init__(self) -> None:
        job_id = _ascii("running Job id", self.job_id)
        if not job_id.startswith("job:") or len(job_id) != 68:
            raise ValueError("running Job id is invalid")
        _digest("running Job hash", self.job_hash)
        _digest("running Job start record", self.start_record_id)
        _digest("running Job permit", self.job_permit_id)

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
            raise ValueError("running Job execution context is invalid")
        return cls(
            job_hash=value["job_hash"],
            job_id=value["job_id"],
            job_permit_id=value["job_permit_id"],
            start_record_id=value["start_record_id"],
        )


def running_job_authority_dependency_paths() -> tuple[Path, ...]:
    """Return the exact project-local semantic closure of this boundary."""

    return tuple(
        sorted(
            {
                _THIS_FILE,
                Path(canonical_module.__file__).resolve(),
                Path(completion_scope_module.__file__).resolve(),
                Path(identity_module.__file__).resolve(),
                Path(permits_module.__file__).resolve(),
                Path(repair_semantic_module.__file__).resolve(),
                Path(effective_scope_module.__file__).resolve(),
                Path(index_module.__file__).resolve(),
                Path(journal_module.__file__).resolve(),
                Path(path_boundary_module.__file__).resolve(),
                Path(state_module.__file__).resolve(),
            },
            key=lambda path: path.as_posix(),
        )
    )


def effective_running_job_implementation(
    index: LocalIndex | LocalIndexView,
    *,
    job_id: str,
    declared_implementation_identity: str,
) -> tuple[str, str | None]:
    """Project the latest typed in-place implementation Repair."""

    _digest("declared Job implementation", declared_implementation_identity)
    head = index.event_head(f"job-repair:{job_id}")
    if head is None:
        return declared_implementation_identity, None
    record = index.get(head.record_kind, head.record_id)
    payload = None if record is None else record.payload
    effective = (
        None
        if not isinstance(payload, Mapping)
        else payload.get("effective_implementation_identity")
    )
    if (
        record is None
        or record.kind != "repair-close"
        or record.status != "repaired"
        or record.subject != f"Job:{job_id}"
        or payload.get("job_id") != job_id
        or not isinstance(effective, str)
    ):
        raise RunningJobAuthorityIntegrityError(
            "running Job implementation Repair projection is invalid"
        )
    _digest("effective Job implementation", effective)
    declaration = index.get("job-declared", job_id)
    spec = None if declaration is None else declaration.payload.get("spec")
    subject = None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
    executable_id = (
        None
        if not isinstance(subject, Mapping)
        or subject.get("kind") != "Executable"
        or type(subject.get("id")) is not str
        else subject["id"]
    )
    production_trial = (
        None if executable_id is None else index.get("trial", executable_id)
    )
    if production_trial is not None:
        validation = payload.get("semantic_equivalence_validation")
        binding = (
            None
            if not isinstance(validation, Mapping)
            else validation.get("binding")
        )
        facts = (
            None
            if not isinstance(validation, Mapping)
            else validation.get("facts")
        )
        trace = (
            None
            if not isinstance(validation, Mapping)
            else validation.get("registry_trace")
        )
        claims = (
            None
            if not isinstance(validation, Mapping)
            else validation.get("claims")
        )
        measurements = (
            None
            if not isinstance(validation, Mapping)
            else validation.get("measurement_artifact_hashes")
        )
        if (
            production_trial.payload.get("engineering_fixture") is not False
            or not isinstance(validation, Mapping)
            or validation.get("schema")
            != "implementation_repair_semantic_equivalence_validation.v1"
            or validation.get("verdict") != "passed"
            or not isinstance(binding, Mapping)
            or not isinstance(facts, Mapping)
            or not isinstance(trace, Mapping)
            or not isinstance(claims, list)
            or not claims
            or claims != sorted(set(claims))
            or facts.get("covered_surface_ids") != claims
            or facts.get("old_implementation_identity")
            != payload.get("previous_effective_implementation_identity")
            or facts.get("new_implementation_identity") != effective
            or binding.get("old_implementation_identity")
            != facts.get("old_implementation_identity")
            or binding.get("new_implementation_identity") != effective
            or binding.get("claims") != claims
            or measurements != binding.get("measurement_artifact_hashes")
            or binding.get("repair_id") != payload.get("repair_id")
            or binding.get("validation_plan_hash")
            != facts.get("validation_plan_hash")
            or binding.get("result_manifest_hash")
            != facts.get("result_manifest_hash")
            or binding.get("surface_inventory_hash")
            != facts.get("surface_inventory_hash")
            or trace.get("validator_id") != binding.get("validator_id")
            or type(trace.get("declared_artifact_count")) is not int
            or trace.get("declared_artifact_count") <= 0
            or trace.get("opened_artifact_count")
            != trace.get("declared_artifact_count")
        ):
            raise RunningJobAuthorityIntegrityError(
                "production implementation Repair lacks complete registered "
                "semantic-equivalence authority"
            )
        try:
            require_passed_semantic_equivalence_facts(
                binding=binding,
                facts=facts,
            )
        except RepairSemanticEquivalenceError as exc:
            raise RunningJobAuthorityIntegrityError(
                "production implementation Repair has invalid changed-artifact "
                "semantic-equivalence authority"
            ) from exc
    return effective, record.record_id


class RunningJobAuthority:
    """Read-only engine capability reconstructed from repository authority."""

    def __init__(
        self,
        root: str | Path,
        *,
        foundation_root: str | Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.foundation_root = (
            Path(foundation_root) if foundation_root is not None else self.root
        )
        self.control = ControlStore(self.root / "state" / "control.json")
        self.journal = DurableJournal(
            self.root / LEGACY_JOURNAL_RELATIVE_PATH,
            create_parent=False,
        )
        self.index_path = self.root / "local" / "index.sqlite"
        self.lock_path = self.root / "local" / "state.writer.lock"

    @staticmethod
    def _assemble(event: Mapping[str, Any]) -> dict[str, Any]:
        sequence = _authority_integer("Journal sequence", event.get("sequence"))
        record_count = _authority_integer(
            "Journal index record count",
            event.get("index_record_count"),
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
        sequence = _authority_integer("Journal sequence", event.get("sequence"))
        offset = _authority_integer(
            "Journal offset",
            event.get("journal_offset"),
            minimum=0,
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

    def _validate_index_record_projection(
        self,
        record: IndexRecord,
        event: Mapping[str, Any],
    ) -> None:
        projected = self._index_mapping(record)
        if record.kind == "journal-event":
            expected = self._index_mapping(self._event_records(event)[0])
            if projected != expected:
                raise RunningJobAuthorityIntegrityError(
                    "journal-event projection differs from authority"
                )
            return
        matches = [item for item in event["index_records"] if item == projected]
        if len(matches) != 1:
            raise RunningJobAuthorityIntegrityError(
                "projection record is not a unique Journal member"
            )

    def _open_authoritative_index(self) -> LocalIndexView:
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
            if (
                type(record.authority_offset) is not int
                or record.authority_offset < 0
                or type(record.authority_sequence) is not int
                or record.authority_sequence < 1
                or type(record.authority_event_id) is not str
                or not record.authority_event_id
            ):
                raise RunningJobAuthorityIntegrityError(
                    "operating projection record lacks Journal authority"
                )
            event = read_authoritative_event(
                record.authority_offset,
                record.authority_sequence,
                record.authority_event_id,
            )
            self._validate_index_record_projection(record, event)

        return LocalIndex.open_read_only(
            self.index_path,
            authority_validator=validate,
        )

    @contextmanager
    def _existing_writer_lock(self) -> Iterator[None]:
        """Coordinate with the writer without creating reader-side state."""

        try:
            with WriterLock(
                self.lock_path,
                create_if_missing=False,
            ):
                yield
        except ControlStateError as exc:
            raise RunningJobAuthorityIntegrityError(
                "existing writer coordination lock is unavailable"
            ) from exc
        except (IndexIntegrityError, LocalIndexError) as exc:
            raise RunningJobAuthorityIntegrityError(
                "existing read-only local index is unavailable"
            ) from exc

    @staticmethod
    def _authority_relative_paths(
        authority: Mapping[str, Any],
    ) -> tuple[str, ...]:
        relative_paths = tuple(
            [authority["operating_direction"]]
            + list(authority["contracts"])
            + list(authority["foundation_inputs"])
        )
        if (
            len(set(relative_paths)) != len(relative_paths)
            or len(
                {
                    item.casefold()
                    for item in relative_paths
                    if type(item) is str
                }
            )
            != len(relative_paths)
        ):
            raise RunningJobAuthorityIntegrityError(
                "authority manifest paths are not portable-unique"
            )
        return relative_paths

    def _authority_manifest_digest(self, authority: Mapping[str, Any]) -> str:
        hashes: dict[str, str] = {}
        root = Path(os.path.abspath(self.foundation_root))
        for relative in self._authority_relative_paths(authority):
            try:
                text = _ascii("authority path", relative)
            except ValueError as exc:
                raise RunningJobAuthorityIntegrityError(
                    "authority path is invalid"
                ) from exc
            canonical = PurePosixPath(text)
            if (
                canonical.is_absolute()
                or canonical.as_posix() != text
                or any(part in {"", ".", ".."} for part in canonical.parts)
                or "\\" in text
                or ":" in text
                or len(text) > 1024
            ):
                raise RunningJobAuthorityIntegrityError(
                    "authority path is not canonical and relative"
                )
            path = root.joinpath(*canonical.parts)
            try:
                content = read_stable_regular_file(path)
            except PathBoundaryError as exc:
                raise RunningJobAuthorityIntegrityError(
                    f"authority input is absent or unsafe: {relative}"
                ) from exc
            assert content is not None
            hashes[relative] = sha256(content).hexdigest()
        return canonical_digest(
            domain="authority-manifest",
            payload=dict(sorted(hashes.items())),
        )

    def _require_stable_locked(self, index: LocalIndexView) -> dict[str, Any]:
        control = self.control.read()
        journal_head, journal_event = self.journal.tail()
        index_head = index.event_head("control")
        if control is None:
            raise RunningJobAuthorityIntegrityError(
                "control is absent or trails durable state"
            )
        if (
            control["authority"].get("manifest_digest")
            != self._authority_manifest_digest(control["authority"])
        ):
            raise RunningJobAuthorityIntegrityError(
                "authority or Foundation input content drifted"
            )
        state_head = control["heads"]["journal"]
        index_state_head = control["heads"]["index"]
        revision = _authority_integer("control revision", control.get("revision"))
        state_sequence = _authority_integer(
            "control journal sequence", state_head.get("sequence")
        )
        required_index_sequence = _authority_integer(
            "control index sequence",
            index_state_head.get("required_sequence"),
        )
        required_record_count = _authority_integer(
            "control index record count",
            index_state_head.get("required_record_count"),
        )
        if required_index_sequence != state_sequence:
            raise RunningJobAuthorityIntegrityError(
                "control index and journal sequences diverge"
            )
        if revision != state_sequence:
            raise RunningJobAuthorityIntegrityError(
                "control revision and journal head diverge"
            )
        if (
            type(journal_head.sequence) is not int
            or journal_head.sequence != state_sequence
            or journal_head.event_id != state_head["event_id"]
        ):
            raise RunningJobAuthorityIntegrityError(
                "control and journal require recovery"
            )
        if journal_event is None or control != seal_control(
            self._assemble(journal_event)
        ):
            raise RunningJobAuthorityIntegrityError(
                "control content differs from journal authority"
            )
        if (
            index_head is None
            or type(index_head.sequence) is not int
            or index_head.sequence != journal_head.sequence
            or index_head.fingerprint != journal_head.event_id
        ):
            raise RunningJobAuthorityIntegrityError(
                "local index requires recovery"
            )
        if index.record_count() != required_record_count:
            raise RunningJobAuthorityIntegrityError(
                "local index contains an unauthoritative record count"
            )
        projection_digest, projection_valid = index.projection_guard()
        if (
            not projection_valid
            or projection_digest
            != control["heads"]["index"]["required_projection_digest"]
        ):
            raise RunningJobAuthorityIntegrityError(
                "local index projection digest requires recovery"
            )
        return control

    @contextmanager
    def open_stable_index(
        self,
    ) -> Iterator[tuple[dict[str, Any], LocalIndexView]]:
        """Yield one stable Journal-authenticated read-only index snapshot."""

        with self._existing_writer_lock():
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                yield _copy(current), index

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
        """Reconstruct a non-runtime engine capability without mutation."""

        if not isinstance(execution, RunningJobExecution):
            raise PermitError("engine entry requires a running Job execution context")
        _ascii("expected callable identity", expected_callable_identity)
        expected_subject: dict[str, str] | None = None
        if expected_evidence_subject is not None:
            if (
                not isinstance(expected_evidence_subject, Mapping)
                or set(expected_evidence_subject) != {"kind", "id"}
            ):
                raise ValueError("expected evidence subject is invalid")
            expected_subject = {
                "kind": _ascii(
                    "expected evidence subject kind",
                    expected_evidence_subject["kind"],
                ),
                "id": _ascii(
                    "expected evidence subject id",
                    expected_evidence_subject["id"],
                ),
            }
        required = tuple(required_input_hashes)
        for item in required:
            _digest("required Job input", item)
        if len(set(required)) != len(required):
            raise ValueError("required Job inputs contain duplicates")

        with self._existing_writer_lock():
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
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
                    or spec.get("callable_identity")
                    != expected_callable_identity
                    or (
                        expected_subject is not None
                        and spec.get("evidence_subject") != expected_subject
                    )
                    or not set(required).issubset(spec.get("input_hashes", []))
                ):
                    raise PermitError(
                        "running Job capability differs from engine entry"
                    )
                effective_implementation, repair_record_id = (
                    effective_running_job_implementation(
                        index,
                        job_id=execution.job_id,
                        declared_implementation_identity=spec[
                            "implementation_identity"
                        ],
                    )
                )
                stream = f"permit:{execution.job_permit_id}"
                issued = index.event_record(stream, 1)
                consumed = index.event_record(stream, 2)
                if issued is None or consumed is None:
                    raise PermitError(
                        "running Job permit provenance is incomplete"
                    )
                engine_entry_id = job.get("engine_entry_record_id")
                engine_entry = (
                    None
                    if not isinstance(engine_entry_id, str)
                    else index.get("job-engine-entry", engine_entry_id)
                )
                resume_record_id = job.get("last_repair_resume_record_id")
                resume_record = (
                    None
                    if not isinstance(resume_record_id, str)
                    else index.get("job-resumed", resume_record_id)
                )
                try:
                    issued_permit = Permit.from_mapping(issued.payload)
                except (KeyError, TypeError, ValueError) as exc:
                    raise PermitError(
                        "running Job issued permit is invalid"
                    ) from exc
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
                    or engine_entry.authority_event_id
                    != start.authority_event_id
                    or engine_entry.authority_sequence
                    != start.authority_sequence
                ):
                    raise PermitError(
                        "running Job permit and start provenance diverge"
                    )
                if repair_record_id is not None and (
                    resume_record is None
                    or resume_record.status != "validated"
                    or resume_record.subject != f"Job:{execution.job_id}"
                    or resume_record.fingerprint != execution.job_hash
                    or resume_record.payload.get("execution")
                    != execution.payload()
                    or resume_record.payload.get("repair_close_record_id")
                    != repair_record_id
                    or resume_record.payload.get(
                        "effective_implementation_identity"
                    )
                    != effective_implementation
                    or resume_record.payload.get("callable_identity")
                    != expected_callable_identity
                ):
                    raise PermitError(
                        "repaired Job has not re-entered its exact engine"
                    )
                return {
                    "batch_id": declaration.payload.get("batch_id"),
                    "effective_implementation_identity": (
                        effective_implementation
                    ),
                    "execution": execution.payload(),
                    "implementation_repair_record_id": repair_record_id,
                    "initiative_id": declaration.payload.get("initiative_id"),
                    "mission_id": declaration.payload.get("mission_id"),
                    "spec": _copy(spec),
                    "study_id": declaration.payload.get("study_id"),
                    "repair_resume_record_id": resume_record_id,
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
            raise ValueError("cache producer execution is invalid")
        for name, value in (
            ("cache output name", cache_output_name),
            ("manifest output name", manifest_output_name),
        ):
            _ascii(name, value)
        _digest("cache hash", cache_hash)
        _digest("cache manifest hash", manifest_hash)
        _ascii("expected cache callable", expected_callable_identity)
        _ascii("expected cache Study", expected_study_id)
        if (
            not isinstance(expected_evidence_subject, Mapping)
            or set(expected_evidence_subject) != {"kind", "id"}
        ):
            raise ValueError("expected cache evidence subject is invalid")
        expected_subject = dict(expected_evidence_subject)
        if any(
            type(value) is not str or not value or not value.isascii()
            for value in expected_subject.values()
        ):
            raise ValueError("expected cache evidence subject is invalid")
        expected_classes = dict(expected_output_classes)
        if not expected_classes or any(
            type(name) is not str
            or not name
            or not name.isascii()
            or storage_class
            not in {"durable_evidence", "reproducible_cache", "transient"}
            for name, storage_class in expected_classes.items()
        ):
            raise ValueError("expected cache output classes are invalid")

        with self._existing_writer_lock():
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                declaration = index.get("job-declared", producer.job_id)
                declared_spec = (
                    None
                    if declaration is None
                    else declaration.payload.get("spec")
                )
                if (
                    declaration is None
                    or declaration.kind != "job-declared"
                    or declaration.record_id != producer.job_id
                    or declaration.status != "declared"
                    or declaration.subject != f"Job:{producer.job_id}"
                    or declaration.fingerprint != producer.job_hash
                    or producer.job_id != f"job:{producer.job_hash}"
                    or declaration.payload.get("mission_id")
                    != current["scientific"]["active_mission"]
                    or declaration.payload.get("study_id")
                    != expected_study_id
                    or not isinstance(declared_spec, dict)
                    or declared_spec.get("runtime_binding") is not None
                    or declared_spec.get("callable_identity")
                    != expected_callable_identity
                    or declared_spec.get("evidence_subject")
                    != expected_subject
                    or set(declared_spec.get("expected_outputs", []))
                    != set(expected_classes)
                    or declared_spec.get("output_classes")
                    != expected_classes
                ):
                    raise RunningJobAuthorityError(
                        "cache producer declaration is unavailable"
                    )
                start = index.get("job-started", producer.start_record_id)
                permit_stream = f"permit:{producer.job_permit_id}"
                issued = index.event_record(permit_stream, 1)
                consumed = index.event_record(permit_stream, 2)
                engine_entry_id = canonical_digest(
                    domain="job-engine-entry",
                    payload=producer.payload(),
                )
                engine_entry = index.get("job-engine-entry", engine_entry_id)
                try:
                    issued_permit = (
                        None
                        if issued is None
                        else Permit.from_mapping(issued.payload)
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise RunningJobAuthorityError(
                        "cache producer start provenance is invalid"
                    ) from exc
                expected_start_id = canonical_digest(
                    domain="job-start",
                    payload={
                        "job_id": producer.job_id,
                        "job_permit": producer.job_permit_id,
                        "runtime_permit": None,
                    },
                )
                if (
                    start is None
                    or start.kind != "job-started"
                    or start.record_id != producer.start_record_id
                    or producer.start_record_id != expected_start_id
                    or start.status != "running"
                    or start.subject != f"Job:{producer.job_id}"
                    or start.fingerprint != producer.job_hash
                    or start.payload
                    != {
                        "job_permit_id": producer.job_permit_id,
                        "runtime": None,
                    }
                    or issued is None
                    or issued.kind != "permit-issued"
                    or issued.status != "issued"
                    or issued.fingerprint != producer.job_permit_id
                    or issued_permit is None
                    or issued_permit.permit_id != producer.job_permit_id
                    or issued_permit.kind is not PermitKind.JOB
                    or issued_permit.subject.kind is not SubjectKind.JOB
                    or issued_permit.subject.subject_id != producer.job_id
                    or issued_permit.input_hash != producer.job_hash
                    or issued_permit.actions != ("start_job",)
                    or not issued_permit.one_shot
                    or consumed is None
                    or consumed.kind != "permit-consumed"
                    or consumed.status != "consumed"
                    or consumed.fingerprint != producer.job_permit_id
                    or consumed.payload
                    != {
                        "one_shot": True,
                        "permit_id": producer.job_permit_id,
                    }
                    or consumed.authority_event_id != start.authority_event_id
                    or consumed.authority_sequence != start.authority_sequence
                    or engine_entry is None
                    or engine_entry.kind != "job-engine-entry"
                    or engine_entry.record_id != engine_entry_id
                    or engine_entry.status != "validated"
                    or engine_entry.subject != f"Job:{producer.job_id}"
                    or engine_entry.fingerprint != producer.job_hash
                    or engine_entry.payload
                    != {
                        "execution": producer.payload(),
                        "permit_consumption_record_id": consumed.record_id,
                    }
                    or engine_entry.authority_event_id
                    != start.authority_event_id
                    or engine_entry.authority_sequence
                    != start.authority_sequence
                ):
                    raise RunningJobAuthorityError(
                        "cache producer start provenance is unavailable"
                    )
                exact_completions = tuple(
                    record
                    for record in index.records_by_fingerprint(
                        producer.job_hash
                    )
                    if record.kind == "job-completed"
                    and record.subject == f"Job:{producer.job_id}"
                    and record.payload.get("job_id") == producer.job_id
                    and record.payload.get("start_record_id")
                    == producer.start_record_id
                )
                completion = (
                    exact_completions[0]
                    if len(exact_completions) == 1
                    else None
                )
                scientific = (
                    None
                    if completion is None
                    else completion.payload.get("scientific")
                )
                failure = (
                    None
                    if completion is None
                    else completion.payload.get("failure")
                )
                scientific_verdict = (
                    None
                    if not isinstance(scientific, dict)
                    else scientific.get("verdict")
                )
                try:
                    effective_scope = (
                        None
                        if completion is None
                        or not isinstance(scientific, dict)
                        else current_study_cache_evidence_scope(
                            index,
                            completion,
                        )
                    )
                except CompletionEvidenceScopeError as exc:
                    raise RunningJobAuthorityIntegrityError(str(exc)) from exc
                if (
                    completion is None
                    or completion.kind != "job-completed"
                    or completion.subject != f"Job:{producer.job_id}"
                    or completion.fingerprint != producer.job_hash
                    or completion.payload.get("job_id") != producer.job_id
                    or completion.payload.get("start_record_id")
                    != producer.start_record_id
                    or set(completion.payload.get("outputs", {}))
                    != set(expected_classes)
                    or completion.payload.get("output_classes")
                    != expected_classes
                    or completion.payload.get("outputs", {}).get(
                        cache_output_name
                    )
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
                    or scientific_verdict
                    not in {"passed", "failed", "not_evaluable"}
                    or effective_scope is None
                    or effective_scope.scientific_eligible is not True
                    or completion.status
                    not in {"success", "failed", "not_evaluable"}
                    or (completion.status == "success" and failure is not None)
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
                            or failure.get("failure_kind")
                            != "not_evaluable"
                        )
                    )
                ):
                    raise RunningJobAuthorityError(
                        "cache producer completion is not validator-derived"
                    )


__all__ = [
    "RunningJobAuthority",
    "RunningJobAuthorityError",
    "RunningJobAuthorityIntegrityError",
    "RunningJobExecution",
    "effective_running_job_implementation",
    "running_job_authority_dependency_paths",
]
