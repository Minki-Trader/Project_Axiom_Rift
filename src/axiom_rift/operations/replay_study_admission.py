"""Read-only admission inspection for an active replay Study.

Legacy replay Studies can predate the implementation-admission boundary.  The
only safe way to continue one is to authenticate the immutable Batch family
and the exact prefix already counted in the Batch trial stream.  This module
does not mutate control state and never grants scientific credit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.scientific_multiplicity_authority import (
    ScientificMultiplicityIntegrityError,
    concurrent_family_executable_ids,
)
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class ReplayStudyAdmissionError(RuntimeError):
    """Replay Study registration authority is malformed."""


class ReplayRegistrationState(str, Enum):
    EMPTY = "empty"
    EXACT_PREFIX = "exact_prefix"
    COMPLETE = "complete"
    COMPLETE_SET_ORDER_DRIFT = "complete_set_order_drift"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayStudyRegistrationInspection:
    """Authenticated registration state for one replay concurrent family."""

    study_id: str
    batch_id: str
    expected_executable_ids: tuple[str, ...]
    registered_executable_ids: tuple[str, ...]
    state: ReplayRegistrationState
    failure_detail: str | None = None
    legacy_lineage_projection: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("study_id", self.study_id),
            ("batch_id", self.batch_id),
        ):
            if type(value) is not str or not value or not value.isascii():
                raise ReplayStudyAdmissionError(f"{name} must be non-empty ASCII")
        if not isinstance(self.state, ReplayRegistrationState):
            raise ReplayStudyAdmissionError("registration state is not typed")
        malformed = self.state is ReplayRegistrationState.MALFORMED
        if (
            type(self.expected_executable_ids) is not tuple
            or (not self.expected_executable_ids and not malformed)
            or len(set(self.expected_executable_ids))
            != len(self.expected_executable_ids)
            or type(self.registered_executable_ids) is not tuple
        ):
            raise ReplayStudyAdmissionError(
                "replay registration family identity is malformed"
            )
        for executable_id in (
            *self.expected_executable_ids,
            *self.registered_executable_ids,
        ):
            if (
                type(executable_id) is not str
                or not executable_id.startswith("executable:")
                or len(executable_id) != 75
            ):
                raise ReplayStudyAdmissionError(
                    "replay registration member identity is malformed"
                )
        if malformed != (self.failure_detail is not None):
            raise ReplayStudyAdmissionError(
                "malformed replay registration needs one exact failure detail"
            )
        if (
            type(self.legacy_lineage_projection) is not bool
            or (malformed and self.legacy_lineage_projection)
        ):
            raise ReplayStudyAdmissionError(
                "replay registration lineage classification is malformed"
            )
        if self.failure_detail is not None and (
            not self.failure_detail or not self.failure_detail.isascii()
        ):
            raise ReplayStudyAdmissionError(
                "replay registration failure detail must be ASCII"
            )
        if (
            not malformed
            and self.state
            is ReplayRegistrationState.COMPLETE_SET_ORDER_DRIFT
        ):
            if (
                len(self.registered_executable_ids)
                != len(self.expected_executable_ids)
                or set(self.registered_executable_ids)
                != set(self.expected_executable_ids)
                or self.registered_executable_ids
                == self.expected_executable_ids
            ):
                raise ReplayStudyAdmissionError(
                    "replay registration order drift is not one exact complete set"
                )
        elif not malformed:
            registered = self.registered_executable_ids
            expected = self.expected_executable_ids
            if registered != expected[: len(registered)]:
                raise ReplayStudyAdmissionError(
                    "replay registration is not an exact family prefix"
                )
            expected_state = (
                ReplayRegistrationState.EMPTY
                if not registered
                else (
                    ReplayRegistrationState.COMPLETE
                    if len(registered) == len(expected)
                    else ReplayRegistrationState.EXACT_PREFIX
                )
            )
            if self.state is not expected_state:
                raise ReplayStudyAdmissionError(
                    "replay registration state differs from its exact prefix"
                )

    @property
    def registered_count(self) -> int:
        return len(self.registered_executable_ids)

    @property
    def started(self) -> bool:
        return self.state in {
            ReplayRegistrationState.EXACT_PREFIX,
            ReplayRegistrationState.COMPLETE,
            ReplayRegistrationState.COMPLETE_SET_ORDER_DRIFT,
        }

    def require_usable(self) -> "ReplayStudyRegistrationInspection":
        if self.state is ReplayRegistrationState.MALFORMED:
            raise ReplayStudyAdmissionError(
                self.failure_detail or "replay registration is malformed"
            )
        if (
            self.state
            is ReplayRegistrationState.COMPLETE_SET_ORDER_DRIFT
            or self.legacy_lineage_projection
        ):
            raise ReplayStudyAdmissionError(
                "replay trial stream is not the exact frozen family prefix"
            )
        return self

    def require_terminal_replacement_usable(
        self,
    ) -> "ReplayStudyRegistrationInspection":
        """Allow an authenticated legacy complete set only to leave the Study."""

        if self.state is ReplayRegistrationState.MALFORMED:
            raise ReplayStudyAdmissionError(
                self.failure_detail or "replay registration is malformed"
            )
        return self


def _malformed(
    *,
    study_id: str,
    batch_id: str,
    expected: tuple[str, ...],
    registered: tuple[str, ...],
    detail: str,
) -> ReplayStudyRegistrationInspection:
    return ReplayStudyRegistrationInspection(
        study_id=study_id,
        batch_id=batch_id,
        expected_executable_ids=expected,
        registered_executable_ids=registered,
        state=ReplayRegistrationState.MALFORMED,
        failure_detail=detail,
    )


def inspect_replay_study_registration(
    index: LocalIndex | LocalIndexView,
    *,
    study_record: IndexRecord,
    batch_record: IndexRecord,
) -> ReplayStudyRegistrationInspection:
    """Classify the exact trial-stream prefix without changing authority."""

    study_id = study_record.record_id
    batch_id = batch_record.record_id
    try:
        family = concurrent_family_executable_ids(batch_record)
    except ScientificMultiplicityIntegrityError as exc:
        family = None
        failure = str(exc)
    else:
        failure = "replay Batch lacks a concurrent family"
    expected = () if family is None else family
    if not expected:
        return _malformed(
            study_id=study_id,
            batch_id=batch_id,
            expected=expected,
            registered=(),
            detail=failure,
        )
    initial_admission_id = study_record.payload.get(
        "replay_implementation_admission_id"
    )
    recertification_stream = (
        f"replay-implementation-admission-study:{study_id}"
    )
    recertification_head = index.event_head(recertification_stream)
    if initial_admission_id is not None and recertification_head is not None:
        return _malformed(
            study_id=study_id,
            batch_id=batch_id,
            expected=expected,
            registered=(),
            detail="replay Study mixes initial and recertified admissions",
        )
    base_admission_id = (
        initial_admission_id
        if initial_admission_id is not None
        else (
            None
            if recertification_head is None
            else recertification_head.record_id
        )
    )
    if base_admission_id is not None:
        admission = (
            None
            if type(base_admission_id) is not str
            else index.get(
                "replay-implementation-admission",
                base_admission_id,
            )
        )
        admission_payload = (
            None if admission is None else admission.payload
        )
        request = (
            None
            if not isinstance(admission_payload, Mapping)
            else admission_payload.get("request")
        )
        manifests = (
            None
            if not isinstance(request, Mapping)
            else request.get("executable_manifests")
        )
        ordered_ids = (
            ()
            if not isinstance(manifests, list)
            or any(not isinstance(item, Mapping) for item in manifests)
            else tuple(
                "executable:"
                + canonical_digest(domain="executable", payload=item)
                for item in manifests
            )
        )
        fingerprint = (
            None
            if not isinstance(admission_payload, Mapping)
            else canonical_digest(
                domain="replay-implementation-admission",
                payload=admission_payload,
            )
        )
        initial_admission = initial_admission_id is not None
        expected_schema = (
            "replay_implementation_admission.v1"
            if initial_admission
            else "replay_implementation_admission.v2"
        )
        boundary_valid = (
            admission is not None
            and (
                (
                    initial_admission
                    and admission.event_stream is None
                    and admission.event_sequence is None
                    and admission.authority_sequence
                    == study_record.authority_sequence
                    and admission.authority_event_id
                    == study_record.authority_event_id
                )
                or (
                    not initial_admission
                    and recertification_head is not None
                    and recertification_head.sequence == 1
                    and recertification_head.record_id
                    == admission.record_id
                    and admission.event_stream == recertification_stream
                    and admission.event_sequence == 1
                    and type(study_record.authority_sequence) is int
                    and type(admission.authority_sequence) is int
                    and study_record.authority_sequence
                    < admission.authority_sequence
                )
            )
        )
        if (
            admission is None
            or admission.kind != "replay-implementation-admission"
            or admission.status != "active"
            or admission.subject != f"Study:{study_id}"
            or admission_payload.get("schema") != expected_schema
            or admission_payload.get("study_id") != study_id
            or admission_payload.get("batch_id") != batch_id
            or admission.fingerprint != fingerprint
            or admission.record_id
            != f"replay-implementation-admission:{fingerprint}"
            or not boundary_valid
            or not ordered_ids
            or len(set(ordered_ids)) != len(ordered_ids)
            or set(ordered_ids) != set(expected)
        ):
            return _malformed(
                study_id=study_id,
                batch_id=batch_id,
                expected=expected,
                registered=(),
                detail=(
                    "replay Study initial implementation admission does not "
                    "bind one exact family execution order"
                ),
            )
        expected = ordered_ids
    replay_obligation_ids = study_record.payload.get("replay_obligation_ids")
    material_identity = study_record.payload.get("material_identity")
    prior_global_multiplicity = study_record.payload.get(
        "prior_global_multiplicity"
    )
    prior_material_trial_count = study_record.payload.get(
        "prior_material_trial_count"
    )
    if (
        study_record.kind != "study-open"
        or study_record.status != "open"
        or batch_record.kind != "batch-open"
        or batch_record.status != "open"
        or batch_record.subject != f"Study:{study_id}"
        or not isinstance(replay_obligation_ids, list)
        or not replay_obligation_ids
        or replay_obligation_ids != sorted(set(replay_obligation_ids))
        or any(type(item) is not str for item in replay_obligation_ids)
        or type(material_identity) is not str
        or not material_identity
        or type(prior_global_multiplicity) is not int
        or prior_global_multiplicity < 0
        or type(prior_material_trial_count) is not int
        or prior_material_trial_count < 0
    ):
        return _malformed(
            study_id=study_id,
            batch_id=batch_id,
            expected=expected,
            registered=(),
            detail="replay Study or Batch declaration is malformed",
        )
    stream = f"batch-trials:{batch_id}"
    head = index.event_head(stream)
    if head is None:
        return ReplayStudyRegistrationInspection(
            study_id=study_id,
            batch_id=batch_id,
            expected_executable_ids=expected,
            registered_executable_ids=(),
            state=ReplayRegistrationState.EMPTY,
        )
    if type(head.sequence) is not int or not 1 <= head.sequence <= len(expected):
        return _malformed(
            study_id=study_id,
            batch_id=batch_id,
            expected=expected,
            registered=(),
            detail="replay trial stream count exceeds its frozen family",
        )
    registered: list[str] = []
    prior_authority_sequence = -1
    prior_accounting_sequence = prior_material_trial_count
    legacy_lineage_projection = False
    study_lineage = {
        name: study_record.payload.get(name)
        for name in (
            "mission_id",
            "portfolio_axis_id",
            "portfolio_axis_identity",
            "portfolio_decision_id",
            "portfolio_snapshot_id",
        )
    }

    def exact_member_lineage_matches(
        executable: object,
        recorded_obligation_ids: object,
    ) -> bool:
        from axiom_rift.research.historical_family_binding import (
            HistoricalFamilyBindingError,
            historical_reference_executable_id_from_manifest,
        )
        from axiom_rift.research.replay_obligation import (
            ReplayObligationError,
            historical_replay_obligation_from_identity_payload,
        )

        if not isinstance(executable, Mapping):
            return False
        try:
            reference = historical_reference_executable_id_from_manifest(
                executable
            )
            if reference is None:
                return False
            matched: list[str] = []
            for obligation_id in replay_obligation_ids:
                obligation_record = index.get(
                    "historical-replay-obligation",
                    obligation_id,
                )
                obligation_payload = (
                    None
                    if obligation_record is None
                    else obligation_record.payload.get("obligation")
                )
                obligation = historical_replay_obligation_from_identity_payload(
                    obligation_payload
                )
                if (
                    obligation_record is None
                    or obligation_record.record_id != obligation.identity
                    or obligation.identity != obligation_id
                    or obligation.governing_mission_id
                    != study_record.payload.get("mission_id")
                ):
                    return False
                if obligation.original_executable_id == reference:
                    matched.append(obligation_id)
        except (
            HistoricalFamilyBindingError,
            ReplayObligationError,
            TypeError,
            ValueError,
        ):
            return False
        if len(matched) > 1:
            return False
        return (
            recorded_obligation_ids == matched
            if matched
            else recorded_obligation_ids is None
        )

    for ordinal in range(1, head.sequence + 1):
        trial = index.event_record(stream, ordinal)
        executable_id = (
            expected[ordinal - 1]
            if trial is None or type(trial.record_id) is not str
            else trial.record_id
        )
        trial_executable = (
            None if trial is None else trial.payload.get("executable")
        )
        trial_executable_id = (
            None
            if not isinstance(trial_executable, Mapping)
            else "executable:"
            + canonical_digest(
                domain="executable",
                payload=trial_executable,
            )
        )
        recorded_replay_obligation_ids = (
            None if trial is None else trial.payload.get("replay_obligation_ids")
        )
        exact_member_lineage = exact_member_lineage_matches(
            trial_executable,
            recorded_replay_obligation_ids,
        )
        legacy_full_lineage = (
            not exact_member_lineage
            and recorded_replay_obligation_ids == replay_obligation_ids
        )
        accounting_id = (
            canonical_digest(
                domain="material-trial",
                payload={
                    "material_identity": material_identity,
                    "executable_id": executable_id,
                },
            )
        )
        accounting = (
            None
            if accounting_id is None
            else index.get("trial-accounting", accounting_id)
        )
        accounting_event = (
            None
            if accounting is None
            or not isinstance(accounting.event_stream, str)
            or type(accounting.event_sequence) is not int
            else index.event_record(
                accounting.event_stream,
                accounting.event_sequence,
            )
        )
        expected_global_multiplicity = (
            None
            if accounting is None
            or type(accounting.event_sequence) is not int
            else prior_global_multiplicity
            + accounting.event_sequence
            - prior_material_trial_count
        )
        try:
            event_kind, operation_result = (
                require_same_event_operation_result(
                    index,
                    record=trial,
                    expected_event_kinds=frozenset({"trial_registered"}),
                )
                if trial is not None
                else (None, None)
            )
        except RecordedTransitionAuthorityError:
            event_kind, operation_result = None, None
        operation_records = (
            ()
            if trial is None or type(trial.authority_sequence) is not int
            else index.records_by_kind_at_authority_sequence(
                "operation",
                trial.authority_sequence,
            )
        )
        operation = (
            operation_records[0] if len(operation_records) == 1 else None
        )
        if (
            trial is None
            or trial.kind != "trial"
            or executable_id not in expected
            or executable_id in registered
            or trial_executable_id != executable_id
            or trial.fingerprint != executable_id.removeprefix("executable:")
            or trial.status != "evaluated"
            or trial.subject != f"Batch:{batch_id}"
            or trial.event_stream != stream
            or trial.event_sequence != ordinal
            or trial.payload.get("study_id") != study_id
            or trial.payload.get("trial_delta") != 1
            or trial.payload.get("engineering_fixture") is not False
            or trial.payload.get("scientific_eligible") is not True
            or trial.payload.get("scheduler_eligible") is not False
            or trial.payload.get("material_identity") != material_identity
            or (not exact_member_lineage and not legacy_full_lineage)
            or any(
                trial.payload.get(name) != value
                for name, value in study_lineage.items()
            )
            or type(trial.authority_sequence) is not int
            or trial.authority_sequence <= prior_authority_sequence
            or accounting is None
            or accounting.kind != "trial-accounting"
            or accounting.record_id != accounting_id
            or accounting.subject != f"Material:{material_identity}"
            or accounting.status != "counted"
            or accounting.fingerprint
            != executable_id.removeprefix("executable:")
            or accounting.payload.get("executable_id") != executable_id
            or accounting.payload.get("study_id") != study_id
            or set(accounting.payload)
            != {"executable_id", "global_multiplicity", "study_id"}
            or type(accounting.payload.get("global_multiplicity")) is not int
            or accounting.payload["global_multiplicity"]
            != expected_global_multiplicity
            or accounting.event_stream != f"material-trial:{material_identity}"
            or type(accounting.event_sequence) is not int
            or accounting.event_sequence <= prior_accounting_sequence
            or accounting_event is None
            or accounting_event.record_id != accounting.record_id
            or accounting.authority_sequence != trial.authority_sequence
            or accounting.authority_event_id != trial.authority_event_id
            or event_kind != "trial_registered"
            or not isinstance(operation_result, Mapping)
            or set(operation_result)
            != {"cache_hit", "global_multiplicity", "trial_delta"}
            or operation_result.get("cache_hit") is not False
            or operation_result.get("trial_delta") != 1
            or operation_result.get("global_multiplicity")
            != expected_global_multiplicity
            or operation is None
            or operation.subject != f"Executable:{executable_id}"
        ):
            return _malformed(
                study_id=study_id,
                batch_id=batch_id,
                expected=expected,
                registered=tuple(registered),
                detail="replay trial stream is not the exact frozen family prefix",
            )
        # The historical full-Study projection is unambiguous for a singleton
        # replay Study because the one selected obligation is also the exact
        # member obligation.  Keep those durable prefixes resumable.  A plural
        # Study that copied the complete obligation list onto every member is
        # genuinely ambiguous and must not continue under exact member lineage.
        legacy_lineage_projection = (
            legacy_lineage_projection
            or (legacy_full_lineage and len(replay_obligation_ids) > 1)
        )
        registered.append(executable_id)
        prior_authority_sequence = trial.authority_sequence
        prior_accounting_sequence = accounting.event_sequence
    if (
        head.record_id != registered[-1]
        or head.fingerprint != registered[-1].removeprefix("executable:")
    ):
        return _malformed(
            study_id=study_id,
            batch_id=batch_id,
            expected=expected,
            registered=tuple(registered),
            detail="replay trial stream head differs from its final prefix member",
        )
    registered_tuple = tuple(registered)
    order_drift = (
        len(registered_tuple) == len(expected)
        and set(registered_tuple) == set(expected)
        and registered_tuple != expected
    )
    if (
        registered_tuple != expected[: len(registered_tuple)]
        and not order_drift
    ):
        return _malformed(
            study_id=study_id,
            batch_id=batch_id,
            expected=expected,
            registered=registered_tuple,
            detail="replay trial stream is not the exact frozen family prefix",
        )
    return ReplayStudyRegistrationInspection(
        study_id=study_id,
        batch_id=batch_id,
        expected_executable_ids=expected,
        registered_executable_ids=registered_tuple,
        state=(
            ReplayRegistrationState.COMPLETE_SET_ORDER_DRIFT
            if order_drift
            else ReplayRegistrationState.COMPLETE
            if len(registered_tuple) == len(expected)
            else ReplayRegistrationState.EXACT_PREFIX
        ),
        legacy_lineage_projection=legacy_lineage_projection,
    )


__all__ = [
    "ReplayRegistrationState",
    "ReplayStudyAdmissionError",
    "ReplayStudyRegistrationInspection",
    "inspect_replay_study_registration",
]
