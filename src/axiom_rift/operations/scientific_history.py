"""Bounded read projections over authoritative scientific history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from axiom_rift.core.canonical import CanonicalValue, canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyBindingError,
    historical_reference_executable_id_from_manifest,
)
from axiom_rift.research.replay_exposure import (
    FrozenFamilyExposureContext,
    ReplayExposureError,
    derive_frozen_registered_family_exposure_context,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class ScientificHistoryProjectionError(RuntimeError):
    """A typed scientific-history relationship is absent or inconsistent."""


@dataclass(frozen=True, slots=True)
class StudyJobEvidenceProjection:
    """Job completions and negative memories bound to one Study."""

    completions: tuple[IndexRecord, ...]
    negative_memories: tuple[IndexRecord, ...]


@dataclass(frozen=True, slots=True)
class BatchJobEvidenceProjection:
    """Exact declarations, completions, and decisions for one Batch."""

    declarations: tuple[IndexRecord, ...]
    completions: tuple[IndexRecord, ...]
    decisions: tuple[IndexRecord, ...]


@dataclass(frozen=True, slots=True)
class HistoricalFamilyMemberExpectation:
    """Stable semantic slot expected in one historical family observation."""

    configuration_id: str
    historical_reference_executable_id: str

    def __post_init__(self) -> None:
        if (
            type(self.configuration_id) is not str
            or not self.configuration_id
            or not self.configuration_id.isascii()
        ):
            raise ValueError("historical family configuration id must be ASCII")
        reference = self.historical_reference_executable_id
        digest = reference.removeprefix("executable:")
        if (
            type(reference) is not str
            or reference == digest
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(
                "historical family reference must be an Executable identity"
            )


@dataclass(frozen=True, slots=True)
class HistoricalExecutableObservation:
    """Immutable audit observation of an Executable already in authority.

    The stored canonical bytes deliberately preserve historical component and
    engine identities.  They are observations, not a claim that current code
    can execute the same implementation.
    """

    ordinal: int
    executable_id: str
    configuration_id: str
    historical_reference_executable_id: str
    authority_sequence: int
    _payload_bytes: bytes

    @property
    def identity(self) -> str:
        return self.executable_id

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        """Return a detached historical payload for audit comparison only."""

        value = parse_canonical(self._payload_bytes)
        if not isinstance(value, dict):
            raise ScientificHistoryProjectionError(
                "historical Executable observation is not an object"
            )
        return value


@dataclass(frozen=True, slots=True)
class HistoricalBatchFamilyObservation:
    """One exact completed Batch family recovered for historical audit."""

    study_id: str
    batch_id: str
    prior_global_exposure_count: int
    first_family_authority_sequence: int
    members: tuple[HistoricalExecutableObservation, ...]
    _batch_spec_bytes: bytes

    @property
    def family_executable_ids(self) -> tuple[str, ...]:
        return tuple(member.executable_id for member in self.members)

    def batch_spec_payload(self) -> dict[str, CanonicalValue]:
        """Return a detached historical Batch specification."""

        value = parse_canonical(self._batch_spec_bytes)
        if not isinstance(value, dict):
            raise ScientificHistoryProjectionError(
                "historical Batch observation is not an object"
            )
        return value


def _historical_executable_identity(value: object) -> str:
    if type(value) is not str:
        raise ScientificHistoryProjectionError(
            "historical Executable identity is malformed"
        )
    digest = value.removeprefix("executable:")
    if value == digest or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ScientificHistoryProjectionError(
            "historical Executable identity is malformed"
        )
    return value


def project_historical_batch_family_observation(
    index: LocalIndex | LocalIndexView,
    *,
    prior_global_exposure_floor: int,
    study_id: str,
    batch_id: str | None,
    expected_members: tuple[HistoricalFamilyMemberExpectation, ...],
    expected_prior_global_exposure_count: int,
    exposure_parameter_name: str | None = None,
) -> HistoricalBatchFamilyObservation:
    """Recover an immutable historical family without current-code substitution.

    The exact Study Batch stream chooses the Batch, its exact ``batch-trials``
    stream chooses and orders members, and the stored concurrent-family
    manifest independently binds those member identities.  Current component
    or engine identities are intentionally never compared with the historical
    payload.  This projection is therefore suitable for audit and exposure
    reconstruction only, never prospective registration or execution.
    """

    if not isinstance(index, (LocalIndex, LocalIndexView)):
        raise TypeError("historical family projection requires LocalIndex")
    if type(study_id) is not str or not study_id or not study_id.isascii():
        raise ScientificHistoryProjectionError(
            "historical family Study id must be non-empty ASCII"
        )
    if batch_id is not None and (
        type(batch_id) is not str or not batch_id or not batch_id.isascii()
    ):
        raise ScientificHistoryProjectionError(
            "historical family Batch id must be non-empty ASCII"
        )
    if (
        type(prior_global_exposure_floor) is not int
        or prior_global_exposure_floor < 0
        or type(expected_prior_global_exposure_count) is not int
        or expected_prior_global_exposure_count < prior_global_exposure_floor
        or type(expected_members) is not tuple
        or not expected_members
        or any(
            not isinstance(member, HistoricalFamilyMemberExpectation)
            for member in expected_members
        )
    ):
        raise ScientificHistoryProjectionError(
            "historical family projection bounds are invalid"
        )
    if exposure_parameter_name is not None and (
        type(exposure_parameter_name) is not str
        or not exposure_parameter_name
        or not exposure_parameter_name.isascii()
    ):
        raise ScientificHistoryProjectionError(
            "historical family exposure parameter must be non-empty ASCII"
        )
    expectation_keys = tuple(
        (
            member.configuration_id,
            member.historical_reference_executable_id,
        )
        for member in expected_members
    )
    if (
        len({key[0] for key in expectation_keys}) != len(expectation_keys)
        or len({key[1] for key in expectation_keys}) != len(expectation_keys)
    ):
        raise ScientificHistoryProjectionError(
            "historical family semantic slots are duplicated"
        )

    resolved_batch_id = batch_id
    if resolved_batch_id is None:
        batch_stream = f"study-batches:{study_id}"
        batch_head = index.event_head(batch_stream)
        if batch_head is None or batch_head.sequence != 1:
            raise ScientificHistoryProjectionError(
                "historical family lacks one exact Study Batch"
            )
        batch_event = index.event_record(batch_stream, 1)
        if (
            batch_event is None
            or batch_event.kind != "batch-open"
            or batch_event.event_stream != batch_stream
            or batch_event.event_sequence != 1
            or batch_event.record_id != batch_head.record_id
            or batch_event.fingerprint != batch_head.fingerprint
        ):
            raise ScientificHistoryProjectionError(
                "historical family Study Batch stream is malformed"
            )
        resolved_batch_id = batch_event.record_id

    batch = index.get("batch-open", resolved_batch_id)
    batch_spec = None if batch is None else batch.payload.get("spec")
    if (
        batch is None
        or batch.kind != "batch-open"
        or batch.record_id != resolved_batch_id
        or batch.subject != f"Study:{study_id}"
        or not isinstance(batch_spec, dict)
        or batch.record_id
        != "batch:" + canonical_digest(domain="batch-spec", payload=batch_spec)
    ):
        raise ScientificHistoryProjectionError(
            "historical family Batch differs from its immutable identity"
        )

    stream = f"batch-trials:{resolved_batch_id}"
    head = index.event_head(stream)
    if head is None or head.sequence != len(expected_members):
        raise ScientificHistoryProjectionError(
            "historical family does not contain the exact expected member count"
        )
    trials: list[IndexRecord] = []
    for ordinal in range(1, head.sequence + 1):
        trial = index.event_record(stream, ordinal)
        if (
            trial is None
            or trial.kind != "trial"
            or trial.status != "evaluated"
            or trial.subject != f"Batch:{resolved_batch_id}"
            or trial.event_stream != stream
            or trial.event_sequence != ordinal
            or trial.payload.get("study_id") != study_id
        ):
            raise ScientificHistoryProjectionError(
                "historical family trial stream is malformed"
            )
        trials.append(trial)
    if (
        trials[-1].record_id != head.record_id
        or trials[-1].fingerprint != head.fingerprint
    ):
        raise ScientificHistoryProjectionError(
            "historical family trial stream head is inconsistent"
        )
    sequences = tuple(trial.authority_sequence for trial in trials)
    if any(type(sequence) is not int or sequence < 1 for sequence in sequences) or tuple(
        sorted(sequences)
    ) != sequences or len(set(sequences)) != len(sequences):
        raise ScientificHistoryProjectionError(
            "historical family trial authority order is invalid"
        )
    first_sequence = sequences[0]
    assert isinstance(first_sequence, int)
    prior_count = index.count_by_kind_before_authority_sequence(
        "trial", first_sequence
    )
    frozen_count = prior_global_exposure_floor + prior_count
    if frozen_count != expected_prior_global_exposure_count:
        raise ScientificHistoryProjectionError(
            "historical family exposure head differs from its fixed authority"
        )
    for sequence in sequences:
        assert isinstance(sequence, int)
        if (
            index.count_by_kind_before_authority_sequence("trial", sequence + 1)
            - index.count_by_kind_before_authority_sequence("trial", sequence)
            != 1
        ):
            raise ScientificHistoryProjectionError(
                "historical family trial authority position is ambiguous"
            )

    acceptance = batch_spec.get("acceptance_profile")
    concurrent = (
        None
        if not isinstance(acceptance, Mapping)
        else acceptance.get("concurrent_family")
    )
    recorded_ids = tuple(trial.record_id for trial in trials)
    if (
        len(set(recorded_ids)) != len(recorded_ids)
        or not isinstance(concurrent, Mapping)
        or concurrent.get("family_size") != len(expected_members)
        or concurrent.get("executable_ids") != list(recorded_ids)
    ):
        raise ScientificHistoryProjectionError(
            "historical family differs from its concurrent-family manifest"
        )

    observations: list[HistoricalExecutableObservation] = []
    for ordinal, (trial, expected) in enumerate(
        zip(trials, expected_members, strict=True),
        start=1,
    ):
        executable_id = _historical_executable_identity(trial.record_id)
        executable = trial.payload.get("executable")
        parameters = (
            None
            if not isinstance(executable, Mapping)
            else executable.get("parameters")
        )
        configuration_id = (
            None
            if not isinstance(parameters, Mapping)
            else parameters.get("configuration_id")
        )
        historical_reference = (
            None
            if not isinstance(parameters, Mapping)
            else parameters.get("historical_reference_executable_id")
        )
        if (
            not isinstance(executable, dict)
            or configuration_id != expected.configuration_id
            or historical_reference
            != expected.historical_reference_executable_id
            or executable_id
            != "executable:"
            + canonical_digest(domain="executable", payload=executable)
            or trial.fingerprint != executable_id.removeprefix("executable:")
        ):
            raise ScientificHistoryProjectionError(
                "historical family member semantic slot is malformed"
            )
        if exposure_parameter_name is not None and (
            parameters.get(exposure_parameter_name)
            != expected_prior_global_exposure_count
        ):
            raise ScientificHistoryProjectionError(
                "historical family member exposure parameter drifted"
            )
        sequence = trial.authority_sequence
        assert isinstance(sequence, int)
        observations.append(
            HistoricalExecutableObservation(
                ordinal=ordinal,
                executable_id=executable_id,
                configuration_id=configuration_id,
                historical_reference_executable_id=historical_reference,
                authority_sequence=sequence,
                _payload_bytes=canonical_bytes(executable),
            )
        )
    return HistoricalBatchFamilyObservation(
        study_id=study_id,
        batch_id=resolved_batch_id,
        prior_global_exposure_count=frozen_count,
        first_family_authority_sequence=first_sequence,
        members=tuple(observations),
        _batch_spec_bytes=canonical_bytes(batch_spec),
    )


def project_frozen_family_exposure_context(
    index: LocalIndex | LocalIndexView,
    *,
    prior_global_exposure_floor: int,
    study_id: str,
    batch_id: str | None,
    expected_family_size: int,
    parameter_name: str | None,
    allow_unregistered: bool,
    allow_partial_registered: bool = False,
) -> FrozenFamilyExposureContext:
    """Recover one replay family's pre-registration trial ordinal.

    Family payloads come only from the exact bounded ``batch-trials`` stream.
    The older project-wide ordinal stays inside a covering SQLite count over
    immutable Journal authority sequence, so no historical trial payload scan
    is needed.  Absence and a non-empty crash-resume prefix are independent
    allowances; normal engine readers accept neither.
    """

    if not isinstance(index, (LocalIndex, LocalIndexView)):
        raise TypeError("fixed-hold exposure projection requires LocalIndex")
    if type(study_id) is not str or not study_id or not study_id.isascii():
        raise ReplayExposureError("replay Study id must be non-empty ASCII")
    if batch_id is not None and (
        type(batch_id) is not str or not batch_id or not batch_id.isascii()
    ):
        raise ReplayExposureError("replay Batch id must be non-empty ASCII")
    if (
        type(allow_unregistered) is not bool
        or type(allow_partial_registered) is not bool
    ):
        raise ReplayExposureError("replay registration allowances must be bool")

    resolved_batch_id = batch_id
    if resolved_batch_id is None:
        batch_stream = f"study-batches:{study_id}"
        batch_head = index.event_head(batch_stream)
        if batch_head is not None:
            if batch_head.sequence != 1:
                raise ScientificHistoryProjectionError(
                    "replay Study Batch history is ambiguous"
                )
            batch = index.event_record(batch_stream, 1)
            if (
                batch is None
                or batch.kind != "batch-open"
                or batch.event_stream != batch_stream
                or batch.event_sequence != 1
            ):
                raise ScientificHistoryProjectionError(
                    "replay Study lost its exact Batch declaration"
                )
            resolved_batch_id = batch.record_id

    if resolved_batch_id is None:
        if not allow_unregistered:
            raise ReplayExposureError("registered replay family is absent")
        return FrozenFamilyExposureContext(
            prior_global_exposure_count=(
                prior_global_exposure_floor + index.count_by_kind("trial")
            ),
            family_executable_ids=(),
            first_family_authority_sequence=None,
        )

    batch = index.get("batch-open", resolved_batch_id)
    batch_spec = None if batch is None else batch.payload.get("spec")
    study = index.get("study-open", study_id)
    batch_digest = (
        None
        if not isinstance(batch_spec, Mapping)
        else canonical_digest(domain="batch-spec", payload=dict(batch_spec))
    )
    if (
        batch is None
        or batch.kind != "batch-open"
        or batch.record_id != resolved_batch_id
        or batch.subject != f"Study:{study_id}"
        or not isinstance(batch_spec, Mapping)
        or batch_digest is None
        or resolved_batch_id != f"batch:{batch_digest}"
        or batch.fingerprint != batch_digest
        or batch.payload.get("batch_hash") != batch_digest
        or study is None
        or study.kind != "study-open"
        or study.record_id != study_id
        or study.subject != f"Study:{study_id}"
        or batch_spec.get("study_hash") != study.fingerprint
    ):
        raise ScientificHistoryProjectionError(
            "replay Batch differs from its Study binding"
        )
    stream = f"batch-trials:{resolved_batch_id}"
    head = index.event_head(stream)
    if head is None:
        if not allow_unregistered:
            raise ReplayExposureError("registered replay family is absent")
        return FrozenFamilyExposureContext(
            prior_global_exposure_count=(
                prior_global_exposure_floor + index.count_by_kind("trial")
            ),
            family_executable_ids=(),
            first_family_authority_sequence=None,
        )
    family: list[IndexRecord] = []
    for ordinal in range(1, head.sequence + 1):
        trial = index.event_record(stream, ordinal)
        if (
            trial is None
            or trial.kind != "trial"
            or trial.status != "evaluated"
            or trial.subject != f"Batch:{resolved_batch_id}"
            or trial.event_stream != stream
            or trial.event_sequence != ordinal
            or trial.payload.get("study_id") != study_id
        ):
            raise ScientificHistoryProjectionError(
                "replay Batch trial history is malformed"
            )
        family.append(trial)
    sequences = tuple(record.authority_sequence for record in family)
    if any(type(sequence) is not int for sequence in sequences) or tuple(
        sorted(sequences)
    ) != sequences:
        raise ScientificHistoryProjectionError(
            "replay Batch trial authority order is invalid"
        )
    first_sequence = sequences[0]
    assert isinstance(first_sequence, int)
    prior_count = index.count_by_kind_before_authority_sequence(
        "trial",
        first_sequence,
    )
    for sequence in sequences:
        assert isinstance(sequence, int)
        before = index.count_by_kind_before_authority_sequence(
            "trial",
            sequence,
        )
        through = index.count_by_kind_before_authority_sequence(
            "trial",
            sequence + 1,
        )
        if through - before != 1:
            raise ScientificHistoryProjectionError(
                "replay trial authority position is ambiguous"
            )
    return derive_frozen_registered_family_exposure_context(
        family_trials=tuple(family),
        prior_global_exposure_floor=prior_global_exposure_floor,
        prior_registered_trial_count=prior_count,
        study_id=study_id,
        expected_family_size=expected_family_size,
        parameter_name=parameter_name,
        require_complete=not allow_partial_registered,
    )


def project_registered_replay_member_bindings(
    index: LocalIndex | LocalIndexView,
    *,
    study_id: str,
    batch_id: str,
) -> tuple[tuple[str, str], ...]:
    """Project the exact durable prospective-to-historical registration prefix."""

    if not isinstance(index, (LocalIndex, LocalIndexView)):
        raise TypeError("replay member binding projection requires LocalIndex")
    if any(
        type(value) is not str or not value or not value.isascii()
        for value in (study_id, batch_id)
    ):
        raise ScientificHistoryProjectionError(
            "replay member binding ids must be non-empty ASCII"
        )
    stream = f"batch-trials:{batch_id}"
    head = index.event_head(stream)
    if head is None or head.sequence < 1:
        raise ScientificHistoryProjectionError(
            "replay member registration prefix is absent"
        )
    bindings: list[tuple[str, str]] = []
    for ordinal in range(1, head.sequence + 1):
        trial = index.event_record(stream, ordinal)
        executable = None if trial is None else trial.payload.get("executable")
        if (
            trial is None
            or trial.kind != "trial"
            or trial.status != "evaluated"
            or trial.subject != f"Batch:{batch_id}"
            or trial.event_stream != stream
            or trial.event_sequence != ordinal
            or trial.payload.get("study_id") != study_id
            or not isinstance(executable, dict)
            or trial.record_id
            != "executable:"
            + canonical_digest(domain="executable", payload=executable)
            or trial.fingerprint
            != trial.record_id.removeprefix("executable:")
        ):
            raise ScientificHistoryProjectionError(
                "replay member registration stream is malformed"
            )
        try:
            historical_reference = (
                historical_reference_executable_id_from_manifest(executable)
            )
        except HistoricalFamilyBindingError as exc:
            raise ScientificHistoryProjectionError(
                "replay member historical binding is malformed"
            ) from exc
        if historical_reference is None:
            raise ScientificHistoryProjectionError(
                "replay member lacks one typed historical binding"
            )
        bindings.append((trial.record_id, historical_reference))
    if (
        bindings[-1][0] != head.record_id
        or trial is None
        or trial.fingerprint != head.fingerprint
        or len({item[0] for item in bindings}) != len(bindings)
        or len({item[1] for item in bindings}) != len(bindings)
    ):
        raise ScientificHistoryProjectionError(
            "replay member registration prefix is inconsistent"
        )
    return tuple(bindings)


def _event_stream_records(
    index: LocalIndex,
    *,
    stream: str,
    required: bool,
) -> tuple[IndexRecord, ...]:
    head = index.event_head(stream)
    if head is None:
        if required:
            raise ScientificHistoryProjectionError(
                f"required scientific history stream is unavailable: {stream}"
            )
        return ()
    if head.sequence < 1:
        raise ScientificHistoryProjectionError(
            f"scientific history stream has an invalid head: {stream}"
        )
    records: list[IndexRecord] = []
    for sequence in range(1, head.sequence + 1):
        record = index.event_record(stream, sequence)
        if record is None:
            raise ScientificHistoryProjectionError(
                f"scientific history stream is not contiguous: {stream}"
            )
        records.append(record)
    latest = records[-1]
    if (
        latest.kind != head.record_kind
        or latest.record_id != head.record_id
        or latest.fingerprint != head.fingerprint
    ):
        raise ScientificHistoryProjectionError(
            f"scientific history stream head is inconsistent: {stream}"
        )
    return tuple(records)


def project_study_job_evidence(
    index: LocalIndex,
    *,
    study_id: str,
) -> StudyJobEvidenceProjection:
    """Follow Study-owned streams instead of scanning project-wide history."""

    batch_records = _event_stream_records(
        index,
        stream=f"study-batches:{study_id}",
        required=True,
    )
    completions: dict[str, IndexRecord] = {}
    memories: dict[str, IndexRecord] = {}
    jobs: set[str] = set()
    for batch in batch_records:
        if batch.kind != "batch-open":
            raise ScientificHistoryProjectionError(
                "Study Batch history contains a non-Batch record"
            )
        budget_records = _event_stream_records(
            index,
            stream=f"batch-budget:{batch.record_id}",
            required=False,
        )
        for reservation in budget_records:
            if reservation.kind != "batch-budget-reservation":
                continue
            job_id = reservation.payload.get("job_id")
            if not isinstance(job_id, str) or job_id in jobs:
                raise ScientificHistoryProjectionError(
                    "Study Job reservation is malformed or duplicated"
                )
            jobs.add(job_id)
            declaration = index.get("job-declared", job_id)
            if (
                declaration is None
                or declaration.payload.get("study_id") != study_id
                or declaration.payload.get("batch_id") != batch.record_id
                or not isinstance(declaration.event_stream, str)
                or declaration.event_sequence != 1
            ):
                raise ScientificHistoryProjectionError(
                    "Study Job reservation lost its exact declaration"
                )
            completion = index.event_record(declaration.event_stream, 2)
            if (
                completion is None
                or completion.kind != "job-completed"
                or completion.payload.get("job_id") != job_id
            ):
                raise ScientificHistoryProjectionError(
                    "Study Job declaration lost its exact completion"
                )
            decisions = tuple(
                record
                for record in index.records_by_fingerprint(
                    completion.fingerprint
                )
                if record.kind == "job-evidence-decision"
                and record.subject == f"Job:{job_id}"
                and record.payload.get("completion_record_id")
                == completion.record_id
            )
            if len(decisions) != 1:
                raise ScientificHistoryProjectionError(
                    "Study Job completion lacks one exact evidence decision"
                )
            completions[completion.record_id] = completion
            memory_id = decisions[0].payload.get("negative_memory_id")
            if memory_id is None:
                continue
            if not isinstance(memory_id, str):
                raise ScientificHistoryProjectionError(
                    "Study Job evidence decision has an invalid negative memory"
                )
            memory = index.get("negative-memory", memory_id)
            if (
                memory is None
                or memory.payload.get("study_id") != study_id
                or completion.record_id
                not in memory.payload.get("evidence_references", ())
            ):
                raise ScientificHistoryProjectionError(
                    "Study Job evidence decision lost its exact negative memory"
                )
            memories[memory.record_id] = memory
    return StudyJobEvidenceProjection(
        completions=tuple(completions.values()),
        negative_memories=tuple(memories.values()),
    )


def project_batch_job_evidence(
    index: LocalIndex,
    *,
    batch_id: str,
) -> BatchJobEvidenceProjection:
    """Follow one Batch reservation stream instead of scanning all Jobs."""

    budget_records = _event_stream_records(
        index,
        stream=f"batch-budget:{batch_id}",
        required=False,
    )
    declarations: list[IndexRecord] = []
    completions: list[IndexRecord] = []
    decisions: list[IndexRecord] = []
    job_ids: set[str] = set()
    for reservation in budget_records:
        if reservation.kind != "batch-budget-reservation":
            continue
        job_id = reservation.payload.get("job_id")
        if not isinstance(job_id, str) or job_id in job_ids:
            raise ScientificHistoryProjectionError(
                "Batch Job reservation is malformed or duplicated"
            )
        job_ids.add(job_id)
        declaration = index.get("job-declared", job_id)
        if (
            declaration is None
            or declaration.payload.get("batch_id") != batch_id
            or declaration.fingerprint != reservation.fingerprint
            or not isinstance(declaration.event_stream, str)
            or type(declaration.event_sequence) is not int
        ):
            raise ScientificHistoryProjectionError(
                "Batch Job reservation lost its exact declaration"
            )
        completion = index.event_record(
            declaration.event_stream,
            declaration.event_sequence + 1,
        )
        if (
            completion is None
            or completion.kind != "job-completed"
            or completion.subject != f"Job:{job_id}"
            or completion.payload.get("job_id") != job_id
            or completion.fingerprint != declaration.fingerprint
        ):
            raise ScientificHistoryProjectionError(
                "Batch Job declaration lost its exact completion"
            )
        evidence_decisions = tuple(
            record
            for record in index.records_by_fingerprint(completion.fingerprint)
            if record.kind == "job-evidence-decision"
            and record.subject == f"Job:{job_id}"
            and record.status in {"continue_batch", "stop_batch"}
            and record.payload.get("completion_record_id")
            == completion.record_id
        )
        if len(evidence_decisions) != 1:
            raise ScientificHistoryProjectionError(
                "Batch Job completion lacks one exact evidence decision"
            )
        declarations.append(declaration)
        completions.append(completion)
        decisions.append(evidence_decisions[0])
    ordered = sorted(
        zip(declarations, completions, decisions, strict=True),
        key=lambda values: values[0].record_id,
    )
    return BatchJobEvidenceProjection(
        declarations=tuple(values[0] for values in ordered),
        completions=tuple(values[1] for values in ordered),
        decisions=tuple(values[2] for values in ordered),
    )


__all__ = [
    "BatchJobEvidenceProjection",
    "HistoricalBatchFamilyObservation",
    "HistoricalExecutableObservation",
    "HistoricalFamilyMemberExpectation",
    "ScientificHistoryProjectionError",
    "StudyJobEvidenceProjection",
    "project_frozen_family_exposure_context",
    "project_batch_job_evidence",
    "project_historical_batch_family_observation",
    "project_registered_replay_member_bindings",
    "project_study_job_evidence",
]
