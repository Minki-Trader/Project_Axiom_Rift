"""Read-only derivation for evidence-bound Portfolio axis dispositions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from axiom_rift.operations.evidence_scope_projection import (
    EvidenceScopeProjectionError,
    effective_completion_evidence_scope,
)
from axiom_rift.operations.executable_axis_lineage import (
    ExecutableAxisLineageError,
    completion_executable_axis_lineage,
    holdout_completion_executable_lineage,
    registered_executable_axis_lineage,
)
from axiom_rift.operations.historical_cost_semantics_reader import (
    HistoricalCostSemanticsProjectionError,
    effective_historical_negative_memory_cost_authority,
)
from axiom_rift.research.axis_disposition import (
    AxisEvidenceKind,
    AxisEvidenceReference,
    AxisEvidenceState,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class AxisDispositionEvidenceError(ValueError):
    """Raised when disposition evidence is absent, stale, or misbound."""


def _effective_scope(index: LocalIndex, completion: IndexRecord):
    try:
        return effective_completion_evidence_scope(index, completion)
    except EvidenceScopeProjectionError as exc:
        raise AxisDispositionEvidenceError(str(exc)) from exc


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
    scope = _effective_scope(index, completion)
    if (
        completion.status != "success"
        or not isinstance(scientific, dict)
        or scope.scientific_eligible is not True
        or not isinstance(adjudication, dict)
        or adjudication.get("schema") != "scientific_adjudication.v1"
        or adjudication.get("candidate_eligible") is not scope.candidate_eligible
        or declaration is None
        or declaration.payload.get("mission_id") != mission_id
    ):
        raise AxisDispositionEvidenceError(
            "axis Job completion lacks current rich scientific authority"
        )
    try:
        lineage = completion_executable_axis_lineage(index, completion)
    except ExecutableAxisLineageError as exc:
        raise AxisDispositionEvidenceError(str(exc)) from exc
    if (
        lineage.mission_id != mission_id
        or lineage.axis_id != axis_id
        or lineage.axis_identity != axis_identity
    ):
        raise AxisDispositionEvidenceError(
            "axis Job completion subject is not bound to its declared Study axis"
        )
    state = _state_from_adjudication(adjudication)
    if (
        scope.cost_semantics_latch_id is not None
        and state is AxisEvidenceState.LOW_INFORMATION
    ):
        state = AxisEvidenceState.UNRESOLVED
    return AxisEvidenceBinding(
        state=state,
        candidate_eligible=scope.candidate_eligible,
        study_ids=(lineage.study_id,),
        executable_ids=(lineage.executable_id,),
        evidence_modes=scope.evidence_modes,
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
    scope = _effective_scope(index, completion)
    if (
        scope.overlay_record_id is not None
        or scope.scientific_eligible is not True
        or scope.scientific_credit != 1
        or scope.terminal_credit
        != (0 if scope.cost_semantics_latch_id is not None else 1)
    ):
        raise AxisDispositionEvidenceError(
            "historical axis adjudication binds a zero-credit completion"
        )
    try:
        lineage = completion_executable_axis_lineage(index, completion)
    except ExecutableAxisLineageError as exc:
        raise AxisDispositionEvidenceError(str(exc)) from exc
    scientific = completion.payload.get("scientific")
    if (
        lineage.mission_id != mission_id
        or lineage.axis_id != axis_id
        or lineage.axis_identity != axis_identity
        or lineage.executable_id != executable_id
        or payload.get("study_id") != lineage.study_id
        or declaration.payload.get("study_id") != lineage.study_id
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
    if (
        scope.cost_semantics_latch_id is not None
        and state is AxisEvidenceState.LOW_INFORMATION
    ):
        state = AxisEvidenceState.UNRESOLVED
    return AxisEvidenceBinding(
        state=state,
        candidate_eligible=False,
        study_ids=(lineage.study_id,),
        executable_ids=(lineage.executable_id,),
        evidence_modes=scope.evidence_modes,
    )


def _negative_memory_binding(
    index: LocalIndex,
    *,
    record: IndexRecord,
    mission_id: str,
    axis_id: str,
    axis_identity: str,
) -> AxisEvidenceBinding:
    try:
        cost_authority = effective_historical_negative_memory_cost_authority(
            index,
            record.record_id,
        )
    except HistoricalCostSemanticsProjectionError as exc:
        raise AxisDispositionEvidenceError(str(exc)) from exc
    executable_id = record.subject.removeprefix("Executable:")
    try:
        registration = registered_executable_axis_lineage(index, executable_id)
    except ExecutableAxisLineageError as exc:
        raise AxisDispositionEvidenceError(str(exc)) from exc
    registration_trial = index.get("trial", registration.executable_id)
    registration_study = index.get("study-open", registration.study_id)
    study_id = record.payload.get("study_id")
    study = (
        None
        if not isinstance(study_id, str)
        else index.get("study-open", study_id)
    )
    evidence_references = record.payload.get("evidence_references")
    memory_holdout_id = record.payload.get("holdout_id")
    modes = _ascii_list(
        "negative-memory evidence modes",
        record.payload.get("executed_evidence_modes"),
    )
    if (
        record.status != "durable"
        or registration.executable_id != executable_id
        or registration.axis_id != axis_id
        or registration.axis_identity != axis_identity
        or registration_trial is None
        or registration_study is None
        or registration_trial.payload.get("portfolio_snapshot_id")
        != registration_study.payload.get("portfolio_snapshot_id")
        or registration_trial.payload.get("material_identity")
        != registration_study.payload.get("material_identity")
        or record.payload.get("mission_id") != mission_id
        or study is None
        or study.kind != "study-open"
        or study.subject != f"Study:{study_id}"
        or study.status not in {"open", "closed"}
        or study.payload.get("portfolio_axis_id") != axis_id
        or study.payload.get("portfolio_axis_identity") != axis_identity
        or study.payload.get("material_identity")
        != registration_trial.payload.get("material_identity")
        or record.payload.get("portfolio_axis_id") != axis_id
        or record.payload.get("portfolio_axis_identity") != axis_identity
        or (
            memory_holdout_id is not None
            and (
                type(memory_holdout_id) is not str
                or not memory_holdout_id
                or not memory_holdout_id.isascii()
            )
        )
        or not isinstance(evidence_references, list)
        or not evidence_references
    ):
        raise AxisDispositionEvidenceError(
            "negative memory is stale or belongs to another axis"
        )
    completion_modes: set[str] = set()
    cost_affected_ids = (
        frozenset()
        if cost_authority is None
        else frozenset(cost_authority.affected_completion_ids)
    )
    has_study_context_evidence = False
    has_holdout_context_evidence = False
    for completion_id in evidence_references:
        completion = (
            None
            if not isinstance(completion_id, str)
            else index.get("job-completed", completion_id)
        )
        scientific = (
            None if completion is None else completion.payload.get("scientific")
        )
        scope = None if completion is None else _effective_scope(index, completion)
        job_id = None if completion is None else completion.payload.get("job_id")
        declaration = (
            None
            if not isinstance(job_id, str)
            else index.get("job-declared", job_id)
        )
        declared_study_id = (
            None if declaration is None else declaration.payload.get("study_id")
        )
        lineage_valid = False
        if isinstance(declared_study_id, str) and completion is not None:
            try:
                lineage = completion_executable_axis_lineage(index, completion)
            except ExecutableAxisLineageError as exc:
                raise AxisDispositionEvidenceError(str(exc)) from exc
            lineage_valid = bool(
                lineage.executable_id == executable_id
                and lineage.mission_id == mission_id
                and lineage.study_id == study_id
                and lineage.axis_id == axis_id
                and lineage.axis_identity == axis_identity
            )
            has_study_context_evidence = True
        elif declared_study_id is None and completion is not None:
            try:
                holdout_lineage = holdout_completion_executable_lineage(
                    index, completion
                )
            except ExecutableAxisLineageError as exc:
                raise AxisDispositionEvidenceError(str(exc)) from exc
            lineage_valid = bool(
                holdout_lineage.executable_id == executable_id
                and holdout_lineage.mission_id == mission_id
                and type(memory_holdout_id) is str
                and holdout_lineage.holdout_id == memory_holdout_id
                and holdout_lineage.registration == registration
            )
            has_holdout_context_evidence = True
        if (
            completion is None
            or completion.status not in {"success", "failed"}
            or not isinstance(scientific, dict)
            or scope is None
            or scope.scientific_eligible is not True
            or scientific.get("verdict") != "failed"
            or scope.candidate_eligible is not False
            or scientific.get("executable_id") != executable_id
            or not lineage_valid
        ):
            raise AxisDispositionEvidenceError(
                "negative memory lacks exact candidate-ineligible falsification"
            )
        if completion_id in cost_affected_ids and (
            scope.negative_memory_authoritative is not False
            or scope.negative_memory_role != "diagnostic_only"
            or scope.cost_semantics_latch_id != cost_authority.latch_record_id
            or scope.terminal_credit != 0
        ):
            raise AxisDispositionEvidenceError(
                "historical cost negative memory retained scientific authority"
            )
        completion_modes.update(
            _ascii_list(
                "negative-memory completion evidence modes",
                list(scope.evidence_modes),
            )
        )
    if not has_study_context_evidence and registration.study_id != study_id:
        raise AxisDispositionEvidenceError(
            "holdout-only negative memory changed its registration Study context"
        )
    if has_holdout_context_evidence != (memory_holdout_id is not None):
        raise AxisDispositionEvidenceError(
            "negative memory holdout context differs from its evidence"
        )
    expected_memory_modes = set(modes)
    if cost_authority is not None:
        if "cost_and_execution" in expected_memory_modes:
            expected_memory_modes.remove("cost_and_execution")
            expected_memory_modes.add("completed_period_proxy_cost")
    if expected_memory_modes != completion_modes:
        raise AxisDispositionEvidenceError(
            "negative-memory evidence modes differ from its completions"
        )
    return AxisEvidenceBinding(
        state=(
            AxisEvidenceState.UNRESOLVED
            if cost_authority is not None
            else AxisEvidenceState.LOW_INFORMATION
        ),
        candidate_eligible=False,
        study_ids=(study_id,),
        executable_ids=(executable_id,),
        evidence_modes=tuple(sorted(expected_memory_modes)),
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
    """Compatibility projection for one Mission axis.

    Multi-axis writer boundaries must use
    :func:`required_axes_scientific_references` so the explicit audit slice is
    decoded once rather than once per axis.
    """

    target = (mission_id, axis_id, axis_identity)
    return required_axes_scientific_references(
        index,
        targets=(target,),
    )[target]


def required_axes_scientific_references(
    index: LocalIndex,
    *,
    targets: tuple[tuple[str, str, str], ...],
) -> dict[tuple[str, str, str], tuple[AxisEvidenceReference, ...]]:
    """Audit every latest scientific interpretation for several axes once.

    This intentionally scans scientific completion history only at the rare
    additive-disposition/terminal boundary.  A caller cannot omit an
    inconvenient partial positive and submit only a negative memory.  The
    complete slice also preserves the prior fail-closed check for malformed
    scientific completions outside any one requested axis.  Callers therefore
    batch all axes at the boundary instead of weakening this into a local
    best-effort lookup or repeating the same global decode per axis.
    """

    if (
        type(targets) is not tuple
        or not targets
        or any(
            type(target) is not tuple
            or len(target) != 3
            or any(
                type(value) is not str or not value or not value.isascii()
                for value in target
            )
            for target in targets
        )
        or len(set(targets)) != len(targets)
    ):
        raise AxisDispositionEvidenceError(
            "axis scientific-reference audit targets are malformed"
        )
    normalized_targets = tuple(sorted(targets))
    required: dict[
        tuple[str, str, str],
        set[tuple[AxisEvidenceKind, str]],
    ] = {target: set() for target in normalized_targets}
    targets_by_mission_axis: dict[
        str,
        dict[str, tuple[tuple[str, str, str], ...]],
    ] = {}
    for mission_id in sorted({target[0] for target in normalized_targets}):
        mission_targets = tuple(
            target for target in normalized_targets if target[0] == mission_id
        )
        targets_by_mission_axis[mission_id] = {
            axis_id: tuple(
                target for target in mission_targets if target[1] == axis_id
            )
            for axis_id in sorted({target[1] for target in mission_targets})
        }

    for completion in index.records_by_kind("job-completed"):
        scientific = completion.payload.get("scientific")
        if (
            not isinstance(scientific, dict)
            or scientific.get("scientific_eligible") is not True
        ):
            continue
        scope = _effective_scope(index, completion)
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
        completion_mission_id = declaration.payload.get("mission_id")
        mission_targets = (
            None
            if not isinstance(completion_mission_id, str)
            else targets_by_mission_axis.get(completion_mission_id)
        )
        if mission_targets is None:
            continue
        declared_study_id = declaration.payload.get("study_id")
        if declared_study_id is None:
            try:
                holdout_lineage = holdout_completion_executable_lineage(
                    index, completion
                )
            except ExecutableAxisLineageError as exc:
                raise AxisDispositionEvidenceError(str(exc)) from exc
            if holdout_lineage.mission_id != completion_mission_id:
                raise AxisDispositionEvidenceError(
                    "Study-less scientific completion changed Mission authority"
                )
            # Holdout outcomes are consumed through candidate or negative-memory
            # authority.  They do not acquire the registration Study's axis merely
            # because the immutable Executable has one counted Trial there.
            continue
        if not isinstance(declared_study_id, str):
            raise AxisDispositionEvidenceError(
                "scientific completion Study binding is malformed"
            )
        try:
            lineage = completion_executable_axis_lineage(index, completion)
        except ExecutableAxisLineageError as exc:
            raise AxisDispositionEvidenceError(str(exc)) from exc
        matching_targets = (
            None
            if not isinstance(lineage.axis_id, str)
            else mission_targets.get(lineage.axis_id)
        )
        if matching_targets is None:
            continue
        if lineage.mission_id != completion_mission_id or any(
            lineage.axis_identity != target[2] for target in matching_targets
        ):
            raise AxisDispositionEvidenceError(
                "scientific completion has stale Portfolio axis lineage"
            )
        if scope.overlay_record_id is not None:
            # Completion-scoped authority takes precedence over any historical
            # adjudication stream.  Neither record may restore scientific or
            # terminal credit removed by the additive overlay.
            continue
        if (
            scope.scientific_eligible is not True
            or scope.scientific_credit != 1
            or scope.terminal_credit != 1
        ):
            continue
        historical_head = index.event_head(
            f"historical-adjudication:{completion.record_id}"
        )
        if historical_head is not None:
            if historical_head.record_kind != "historical-scientific-adjudication":
                raise AxisDispositionEvidenceError(
                    "historical adjudication stream head is malformed"
                )
            for target in matching_targets:
                required[target].add(
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
        for target in matching_targets:
            required[target].add(
                (AxisEvidenceKind.JOB_COMPLETION, completion.record_id)
            )
    return {
        target: tuple(
            AxisEvidenceReference(kind=kind, record_id=record_id)
            for kind, record_id in sorted(
                required[target], key=lambda item: (item[0].value, item[1])
            )
        )
        for target in normalized_targets
    }


__all__ = [
    "AxisDispositionEvidenceError",
    "AxisEvidenceBinding",
    "aggregate_axis_evidence_state",
    "derive_axis_evidence_binding",
    "required_axis_scientific_references",
    "required_axes_scientific_references",
]
