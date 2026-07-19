"""Read-only claim-scoped Study diagnosis projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.operations.effective_scientific_diagnosis import (
    EffectiveScientificDiagnosisError,
    diagnose_effective_scientific_adjudications,
)
from axiom_rift.operations.evidence_scope_projection import (
    EvidenceScopeProjectionError,
    effective_completion_evidence_scope,
)
from axiom_rift.operations.scientific_history import (
    ScientificHistoryProjectionError,
    project_study_job_evidence,
)
from axiom_rift.research.portfolio_projection import (
    PortfolioProjectionError,
    executable_from_identity_payload,
)
from axiom_rift.research.scientific_diagnosis import ScientificDiagnosisPattern
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class StudyDiagnosisProjectionError(ValueError):
    """Raised when durable Study evidence cannot be projected exactly."""


def study_primary_scientific_completions(
    index: LocalIndex | LocalIndexView,
    *,
    study_id: str,
) -> tuple[IndexRecord, ...]:
    """Select disposition-driving completions from durable role authority."""

    try:
        job_evidence = project_study_job_evidence(index, study_id=study_id)
    except ScientificHistoryProjectionError as exc:
        raise StudyDiagnosisProjectionError(str(exc)) from exc
    completions = job_evidence.completions
    study = index.get("study-open", study_id)
    if study is None:
        raise StudyDiagnosisProjectionError(
            "Study claim-scoped diagnosis lost its Study"
        )
    admission_id = study.payload.get("replay_implementation_admission_id")
    if not isinstance(admission_id, str):
        return tuple(completions)

    admission = index.get("replay-implementation-admission", admission_id)
    semantic = study.payload.get("semantic_proposal")
    family = (
        None
        if not isinstance(semantic, Mapping)
        else semantic.get("concurrent_family")
    )
    target_reference = (
        None
        if not isinstance(family, Mapping)
        else family.get("target_historical_executable_id")
    )
    request = None if admission is None else admission.payload.get("request")
    manifests = (
        None
        if not isinstance(request, Mapping)
        else request.get("executable_manifests")
    )
    if (
        admission is None
        or not isinstance(target_reference, str)
        or not isinstance(manifests, list)
    ):
        raise StudyDiagnosisProjectionError(
            "replay diagnosis target authority is malformed"
        )
    target_ids: list[str] = []
    try:
        for manifest in manifests:
            if not isinstance(manifest, Mapping):
                raise PortfolioProjectionError(
                    "replay executable manifest is malformed"
                )
            parameters = manifest.get("parameters")
            if (
                isinstance(parameters, Mapping)
                and parameters.get("historical_reference_executable_id")
                == target_reference
            ):
                target_ids.append(
                    executable_from_identity_payload(manifest).identity
                )
    except PortfolioProjectionError as exc:
        raise StudyDiagnosisProjectionError(str(exc)) from exc
    if len(target_ids) != 1:
        raise StudyDiagnosisProjectionError(
            "replay diagnosis target is ambiguous"
        )
    completions = tuple(
        completion
        for completion in completions
        if isinstance(completion.payload.get("scientific"), Mapping)
        and completion.payload["scientific"].get("executable_id")
        == target_ids[0]
    )
    if len(completions) != 1:
        raise StudyDiagnosisProjectionError(
            "replay diagnosis target completion is unavailable"
        )
    return completions


def study_claim_scoped_diagnosis(
    index: LocalIndex | LocalIndexView,
    *,
    study_id: str,
) -> ScientificDiagnosisPattern | None:
    """Derive the standard primary-question diagnosis without state mutation."""

    completions = study_primary_scientific_completions(
        index,
        study_id=study_id,
    )
    scoped_adjudications: list[tuple[Mapping[str, Any], Any]] = []
    for completion in completions:
        scientific = completion.payload.get("scientific")
        adjudication = (
            None
            if not isinstance(scientific, Mapping)
            else scientific.get("adjudication")
        )
        if isinstance(adjudication, Mapping):
            try:
                scope = effective_completion_evidence_scope(index, completion)
            except EvidenceScopeProjectionError as exc:
                raise StudyDiagnosisProjectionError(
                    "Study claim-scoped diagnosis scope is malformed"
                ) from exc
            scoped_adjudications.append((adjudication, scope))
    if not scoped_adjudications:
        return None
    try:
        pattern = diagnose_effective_scientific_adjudications(
            tuple(scoped_adjudications)
        )
    except EffectiveScientificDiagnosisError as exc:
        raise StudyDiagnosisProjectionError(
            "Study claim-scoped diagnosis evidence is malformed"
        ) from exc
    return pattern if pattern.primary_question_recognized else None


__all__ = [
    "StudyDiagnosisProjectionError",
    "study_claim_scoped_diagnosis",
    "study_primary_scientific_completions",
]
