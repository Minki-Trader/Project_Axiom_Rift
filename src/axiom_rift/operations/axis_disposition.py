"""Read-only derivation for evidence-bound Portfolio axis dispositions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from axiom_rift.research.axis_disposition import (
    AxisEvidenceKind,
    AxisEvidenceReference,
    AxisEvidenceState,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class AxisDispositionEvidenceError(ValueError):
    """Raised when disposition evidence is absent, stale, or misbound."""


@dataclass(frozen=True, slots=True)
class AxisEvidenceBinding:
    """Writer-verifiable facts derived from one durable evidence reference."""

    state: AxisEvidenceState
    candidate_eligible: bool
    study_ids: tuple[str, ...]
    executable_ids: tuple[str, ...]
    evidence_modes: tuple[str, ...]
    negative_memory_ids: tuple[str, ...] = ()


_STATE_PRIORITY = {
    AxisEvidenceState.LOW_INFORMATION: 0,
    AxisEvidenceState.NOT_EVALUABLE: 1,
    AxisEvidenceState.INVALID: 2,
    AxisEvidenceState.UNRESOLVED: 3,
    AxisEvidenceState.PARTIAL_POSITIVE: 4,
    AxisEvidenceState.FRONTIER: 5,
}


def aggregate_axis_evidence_state(
    bindings: tuple[AxisEvidenceBinding, ...],
) -> AxisEvidenceState:
    """Keep the most informative unresolved state instead of averaging it away."""

    if not bindings:
        raise AxisDispositionEvidenceError("axis disposition has no evidence bindings")
    return max((item.state for item in bindings), key=_STATE_PRIORITY.__getitem__)


def _ascii_list(name: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        type(item) is not str or not item or not item.isascii() for item in value
    ):
        raise AxisDispositionEvidenceError(f"{name} is malformed")
    if len(set(value)) != len(value):
        raise AxisDispositionEvidenceError(f"{name} contains duplicates")
    return tuple(sorted(value))


def _require_trial_binding(
    index: LocalIndex,
    *,
    executable_id: object,
    mission_id: str,
    axis_id: str,
    axis_identity: str,
) -> tuple[IndexRecord, str]:
    if type(executable_id) is not str:
        raise AxisDispositionEvidenceError("axis evidence executable is absent")
    trial = index.get("trial", executable_id)
    study_id = None if trial is None else trial.payload.get("study_id")
    study = (
        None
        if not isinstance(study_id, str)
        else index.get("study-open", study_id)
    )
    if (
        trial is None
        or trial.status != "evaluated"
        or trial.payload.get("mission_id") != mission_id
        or trial.payload.get("portfolio_axis_id") != axis_id
        or trial.payload.get("portfolio_axis_identity") != axis_identity
        or study is None
        or study.payload.get("mission_id") != mission_id
        or study.payload.get("portfolio_axis_id") != axis_id
        or study.payload.get("portfolio_axis_identity") != axis_identity
    ):
        raise AxisDispositionEvidenceError(
            "axis evidence trial is stale or belongs to another axis"
        )
    return trial, study_id


def _state_from_adjudication(value: Mapping[str, Any]) -> AxisEvidenceState:
    state = value.get("state")
    invalid_metrics = value.get("invalid_metrics")
    if state == "frontier":
        return AxisEvidenceState.FRONTIER
    if state == "confirmed":
        return AxisEvidenceState.FRONTIER
    if state == "partial_positive":
        return AxisEvidenceState.PARTIAL_POSITIVE
    if state == "unresolved":
        return AxisEvidenceState.UNRESOLVED
    if state == "not_evaluable":
        return (
            AxisEvidenceState.INVALID
            if isinstance(invalid_metrics, list) and bool(invalid_metrics)
            else AxisEvidenceState.NOT_EVALUABLE
        )
    if state == "contradicted":
        return AxisEvidenceState.LOW_INFORMATION
    raise AxisDispositionEvidenceError("scientific adjudication state is invalid")


def _job_completion_binding(
    index: LocalIndex,
    *,
    completion: IndexRecord,
    mission_id: str,
    axis_id: str,
    axis_identity: str,
) -> AxisEvidenceBinding:
    scientific = completion.payload.get("scientific")
    job_id = completion.payload.get("job_id")
    declaration = (
        None if not isinstance(job_id, str) else index.get("job-declared", job_id)
    )
    adjudication = (
        None if not isinstance(scientific, dict) else scientific.get("adjudication")
    )
    candidate_eligible = (
        None
        if not isinstance(scientific, dict)
        else scientific.get("candidate_eligible")
    )
    if (
        completion.status != "success"
        or not isinstance(scientific, dict)
        or scientific.get("scientific_eligible") is not True
        or not isinstance(adjudication, dict)
        or adjudication.get("schema") != "scientific_adjudication.v1"
        or type(candidate_eligible) is not bool
        or adjudication.get("candidate_eligible") is not candidate_eligible
        or declaration is None
        or declaration.payload.get("mission_id") != mission_id
    ):
        raise AxisDispositionEvidenceError(
            "axis Job completion lacks current rich scientific authority"
        )
    executable_id = scientific.get("executable_id")
    _, study_id = _require_trial_binding(
        index,
        executable_id=executable_id,
        mission_id=mission_id,
        axis_id=axis_id,
        axis_identity=axis_identity,
    )
    spec = declaration.payload.get("spec")
    if (
        declaration.payload.get("study_id") != study_id
        or not isinstance(spec, dict)
        or spec.get("evidence_subject")
        != {"kind": "Executable", "id": executable_id}
    ):
        raise AxisDispositionEvidenceError(
            "axis Job completion subject is not bound to its trial"
        )
    modes = _ascii_list(
        "axis Job completion evidence modes",
        scientific.get("executed_evidence_modes"),
    )
    return AxisEvidenceBinding(
        state=_state_from_adjudication(adjudication),
        candidate_eligible=candidate_eligible,
        study_ids=(study_id,),
        executable_ids=(executable_id,),
        evidence_modes=modes,
    )


def _historical_adjudication_binding(
    index: LocalIndex,
    *,
    record: IndexRecord,
    mission_id: str,
    axis_id: str,
    axis_identity: str,
) -> AxisEvidenceBinding:
    payload = record.payload
    completion_id = payload.get("completion_record_id")
    completion = (
        None
        if not isinstance(completion_id, str)
        else index.get("job-completed", completion_id)
    )
    job_id = None if completion is None else completion.payload.get("job_id")
    declaration = (
        None if not isinstance(job_id, str) else index.get("job-declared", job_id)
    )
    adjudication = payload.get("adjudication")
    executable_id = payload.get("executable_id")
    head = (
        None
        if not isinstance(completion_id, str)
        else index.event_head(f"historical-adjudication:{completion_id}")
    )
    if (
        completion is None
        or declaration is None
        or declaration.payload.get("mission_id") != mission_id
        or not isinstance(adjudication, dict)
        or adjudication.get("candidate_eligible") is not False
        or head is None
        or head.record_kind != "historical-scientific-adjudication"
        or head.record_id != record.record_id
    ):
        raise AxisDispositionEvidenceError(
            "historical axis adjudication is stale or not candidate-ineligible"
        )
    _, study_id = _require_trial_binding(
        index,
        executable_id=executable_id,
        mission_id=mission_id,
        axis_id=axis_id,
        axis_identity=axis_identity,
    )
    scientific = completion.payload.get("scientific")
    if (
        payload.get("study_id") != study_id
        or declaration.payload.get("study_id") != study_id
        or not isinstance(scientific, dict)
    ):
        raise AxisDispositionEvidenceError(
            "historical axis adjudication does not bind its original Study"
        )
    effective_state = payload.get("effective_state")
    if effective_state == "not_evaluable":
        validity_overrides = payload.get("validity_overrides")
        invalid_metrics = adjudication.get("invalid_metrics")
        state = (
            AxisEvidenceState.INVALID
            if (isinstance(validity_overrides, list) and bool(validity_overrides))
            or (isinstance(invalid_metrics, list) and bool(invalid_metrics))
            else AxisEvidenceState.NOT_EVALUABLE
        )
    elif effective_state == "partial_positive":
        state = AxisEvidenceState.PARTIAL_POSITIVE
    elif effective_state == "unresolved":
        state = AxisEvidenceState.UNRESOLVED
    elif effective_state in {"frontier", "confirmed"}:
        state = AxisEvidenceState.FRONTIER
    elif effective_state == "contradicted":
        state = AxisEvidenceState.LOW_INFORMATION
    else:
        raise AxisDispositionEvidenceError(
            "historical axis adjudication effective state is invalid"
        )
    modes = _ascii_list(
        "historical axis evidence modes",
        scientific.get("executed_evidence_modes"),
    )
    return AxisEvidenceBinding(
        state=state,
        candidate_eligible=False,
        study_ids=(study_id,),
        executable_ids=(executable_id,),
        evidence_modes=modes,
    )


def _negative_memory_binding(
    index: LocalIndex,
    *,
    record: IndexRecord,
    mission_id: str,
    axis_id: str,
    axis_identity: str,
) -> AxisEvidenceBinding:
    executable_id = record.subject.removeprefix("Executable:")
    _, study_id = _require_trial_binding(
        index,
        executable_id=executable_id,
        mission_id=mission_id,
        axis_id=axis_id,
        axis_identity=axis_identity,
    )
    evidence_references = record.payload.get("evidence_references")
    modes = _ascii_list(
        "negative-memory evidence modes",
        record.payload.get("executed_evidence_modes"),
    )
    if (
        record.status != "durable"
        or record.payload.get("mission_id") != mission_id
        or record.payload.get("study_id") != study_id
        or record.payload.get("portfolio_axis_id") != axis_id
        or record.payload.get("portfolio_axis_identity") != axis_identity
        or not isinstance(evidence_references, list)
        or not evidence_references
    ):
        raise AxisDispositionEvidenceError(
            "negative memory is stale or belongs to another axis"
        )
    completion_modes: set[str] = set()
    for completion_id in evidence_references:
        completion = (
            None
            if not isinstance(completion_id, str)
            else index.get("job-completed", completion_id)
        )
        scientific = (
            None if completion is None else completion.payload.get("scientific")
        )
        if (
            completion is None
            or completion.status not in {"success", "failed"}
            or not isinstance(scientific, dict)
            or scientific.get("scientific_eligible") is not True
            or scientific.get("verdict") != "failed"
            or scientific.get("candidate_eligible") is not False
            or scientific.get("executable_id") != executable_id
        ):
            raise AxisDispositionEvidenceError(
                "negative memory lacks exact candidate-ineligible falsification"
            )
        completion_modes.update(
            _ascii_list(
                "negative-memory completion evidence modes",
                scientific.get("executed_evidence_modes"),
            )
        )
    if set(modes) != completion_modes:
        raise AxisDispositionEvidenceError(
            "negative-memory evidence modes differ from its completions"
        )
    return AxisEvidenceBinding(
        state=AxisEvidenceState.LOW_INFORMATION,
        candidate_eligible=False,
        study_ids=(study_id,),
        executable_ids=(executable_id,),
        evidence_modes=modes,
        negative_memory_ids=(record.record_id,),
    )


def derive_axis_evidence_binding(
    index: LocalIndex,
    *,
    reference: AxisEvidenceReference,
    mission_id: str,
    axis_id: str,
    axis_identity: str,
) -> AxisEvidenceBinding:
    """Resolve one typed reference and prove its exact Mission/axis lineage."""

    record = index.get(reference.kind.value, reference.record_id)
    if record is None:
        raise AxisDispositionEvidenceError("axis disposition evidence is unavailable")
    if reference.kind is AxisEvidenceKind.JOB_COMPLETION:
        return _job_completion_binding(
            index,
            completion=record,
            mission_id=mission_id,
            axis_id=axis_id,
            axis_identity=axis_identity,
        )
    if reference.kind is AxisEvidenceKind.HISTORICAL_ADJUDICATION:
        return _historical_adjudication_binding(
            index,
            record=record,
            mission_id=mission_id,
            axis_id=axis_id,
            axis_identity=axis_identity,
        )
    if reference.kind is AxisEvidenceKind.NEGATIVE_MEMORY:
        return _negative_memory_binding(
            index,
            record=record,
            mission_id=mission_id,
            axis_id=axis_id,
            axis_identity=axis_identity,
        )
    raise AxisDispositionEvidenceError("axis evidence kind is unsupported")


def required_axis_scientific_references(
    index: LocalIndex,
    *,
    mission_id: str,
    axis_id: str,
    axis_identity: str,
) -> tuple[AxisEvidenceReference, ...]:
    """Return every latest scientific interpretation on one Mission axis.

    This intentionally scans scientific completion history only at the rare
    additive-disposition/terminal boundary.  A caller cannot omit an
    inconvenient partial positive and submit only a negative memory.
    """

    required: set[tuple[AxisEvidenceKind, str]] = set()
    for completion in index.records_by_kind("job-completed"):
        scientific = completion.payload.get("scientific")
        if (
            not isinstance(scientific, dict)
            or scientific.get("scientific_eligible") is not True
        ):
            continue
        job_id = completion.payload.get("job_id")
        declaration = (
            None
            if not isinstance(job_id, str)
            else index.get("job-declared", job_id)
        )
        if declaration is None:
            raise AxisDispositionEvidenceError(
                "scientific completion lacks its Job declaration"
            )
        if declaration.payload.get("mission_id") != mission_id:
            continue
        executable_id = scientific.get("executable_id")
        if not isinstance(executable_id, str):
            raise AxisDispositionEvidenceError(
                "scientific completion lacks its Executable"
            )
        trial = index.get("trial", executable_id)
        if trial is None:
            raise AxisDispositionEvidenceError(
                "scientific completion lacks its counted trial"
            )
        trial_axis_id = trial.payload.get("portfolio_axis_id")
        trial_axis_identity = trial.payload.get("portfolio_axis_identity")
        if trial_axis_id != axis_id:
            continue
        if (
            trial.payload.get("mission_id") != mission_id
            or trial_axis_identity != axis_identity
        ):
            raise AxisDispositionEvidenceError(
                "scientific completion has stale Portfolio axis lineage"
            )
        historical_head = index.event_head(
            f"historical-adjudication:{completion.record_id}"
        )
        if historical_head is not None:
            if historical_head.record_kind != "historical-scientific-adjudication":
                raise AxisDispositionEvidenceError(
                    "historical adjudication stream head is malformed"
                )
            required.add(
                (
                    AxisEvidenceKind.HISTORICAL_ADJUDICATION,
                    historical_head.record_id,
                )
            )
            continue
        adjudication = scientific.get("adjudication")
        if not isinstance(adjudication, dict):
            raise AxisDispositionEvidenceError(
                "legacy scientific completion lacks its additive adjudication"
            )
        required.add((AxisEvidenceKind.JOB_COMPLETION, completion.record_id))
    return tuple(
        AxisEvidenceReference(kind=kind, record_id=record_id)
        for kind, record_id in sorted(
            required, key=lambda item: (item[0].value, item[1])
        )
    )


__all__ = [
    "AxisDispositionEvidenceError",
    "AxisEvidenceBinding",
    "aggregate_axis_evidence_state",
    "derive_axis_evidence_binding",
    "required_axis_scientific_references",
]
