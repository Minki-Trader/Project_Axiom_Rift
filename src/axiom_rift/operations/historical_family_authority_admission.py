"""Writer-side admission for immutable historical family authorities."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from axiom_rift.core.identity import canonical_digest
from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilyBindingError,
    historical_family_authority_from_payload,
    historical_family_core_identity,
)
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE,
    HISTORICAL_FAMILY_IDENTITY_BY_MODULE,
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)
from axiom_rift.research.replay_obligation import (
    historical_replay_obligation_from_identity_payload,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView
from axiom_rift.storage.evidence import EvidenceStore


class HistoricalFamilyAuthorityAdmissionError(ValueError):
    """One proposed authority is absent, stale, or historically false."""


def _require_cross_study_family_evidence_bridge(
    *,
    repository_root: Path,
    index: LocalIndex,
    obligation: object,
    authority: HistoricalFamilyAuthority,
) -> None:
    """Prove a later Study consumed an exact earlier concurrent family.

    A repair Study can reuse a previously registered Executable and therefore
    have a one-trial Batch even though its scientific surface still evaluates
    the exact earlier concurrent family.  The family origin and obligation
    Study are distinct facts; this bridge authenticates both rather than
    rewriting either identity.
    """

    original_study_id = getattr(obligation, "original_study_id", None)
    original_completion_id = getattr(
        obligation,
        "original_completion_record_id",
        None,
    )
    original_executable_id = getattr(
        obligation,
        "original_executable_id",
        None,
    )
    family = authority.family
    if family.original_study_id == original_study_id:
        return
    completion = (
        None
        if not isinstance(original_completion_id, str)
        else index.get("job-completed", original_completion_id)
    )
    job_id = None if completion is None else completion.payload.get("job_id")
    declaration = (
        None
        if not isinstance(job_id, str)
        else index.get("job-declared", job_id)
    )
    outputs = None if completion is None else completion.payload.get("outputs")
    scientific = (
        None if completion is None else completion.payload.get("scientific")
    )
    spec = None if declaration is None else declaration.payload.get("spec")
    subject = None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
    if (
        completion is None
        or completion.status not in {"success", "failed", "not_evaluable"}
        or declaration is None
        or declaration.payload.get("study_id") != original_study_id
        or not isinstance(subject, Mapping)
        or subject.get("id") != original_executable_id
        or not isinstance(outputs, Mapping)
        or not outputs
        or set(outputs) != set(spec.get("expected_outputs", ()))
        or not isinstance(scientific, Mapping)
        or scientific.get("executable_id") != original_executable_id
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "cross-Study historical family bridge lacks its exact completion"
        )
    expected_ids = tuple(
        member.historical_reference_executable_id for member in family.members
    )
    expected_set = set(expected_ids)
    store = EvidenceStore(repository_root / "local" / "evidence")
    parsed_outputs: dict[str, object] = {}
    try:
        for output_hash in outputs.values():
            if not isinstance(output_hash, str):
                raise ValueError("output hash is not text")
            parsed_outputs[output_hash] = parse_canonical(
                store.read_verified(output_hash)
            )
    except (OSError, TypeError, ValueError) as exc:
        raise HistoricalFamilyAuthorityAdmissionError(
            "cross-Study historical family bridge evidence is unavailable"
        ) from exc

    surfaces: list[tuple[str, Mapping[str, object]]] = []
    for output_hash, value in parsed_outputs.items():
        if not isinstance(value, Mapping):
            continue
        evaluations = value.get("evaluations")
        selection = value.get("selection_context")
        if not isinstance(evaluations, list) or not isinstance(selection, list):
            continue
        evaluation_ids = tuple(
            item.get("subject_executable_id")
            for item in evaluations
            if isinstance(item, Mapping)
        )
        selection_ids = tuple(
            item.get("executable_id")
            for item in selection
            if isinstance(item, Mapping)
        )
        if (
            len(evaluation_ids) == len(expected_ids)
            and len(selection_ids) == len(expected_ids)
            and set(evaluation_ids) == expected_set
            and set(selection_ids) == expected_set
            and len(set(evaluation_ids)) == len(expected_ids)
            and len(set(selection_ids)) == len(expected_ids)
        ):
            surfaces.append((output_hash, value))
    if len(surfaces) != 1:
        raise HistoricalFamilyAuthorityAdmissionError(
            "cross-Study historical family bridge surface is ambiguous"
        )
    surface_hash, _surface = surfaces[0]
    projections = tuple(
        value
        for value in parsed_outputs.values()
        if isinstance(value, Mapping)
        and value.get("subject_executable_id") == original_executable_id
        and value.get("surface_artifact_hash") == surface_hash
        and isinstance(value.get("selection_context"), list)
        and {
            item.get("executable_id")
            for item in value["selection_context"]
            if isinstance(item, Mapping)
        }
        == expected_set
    )
    if len(projections) != 1:
        raise HistoricalFamilyAuthorityAdmissionError(
            "cross-Study historical family bridge projection is ambiguous"
        )


def require_recorded_historical_family_authority(
    index: LocalIndex | LocalIndexView,
    record: IndexRecord,
) -> HistoricalFamilyAuthority:
    """Authenticate one accepted family authority and its Writer event."""

    try:
        authority = historical_family_authority_from_payload(record.payload)
        event_kind, result = require_same_event_operation_result(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {
                    "historical_replay_family_authorities_registered",
                    "historical_replay_satisfaction_invalidated",
                    "historical_replay_sibling_evidence_recertified",
                }
            ),
        )
    except (
        HistoricalFamilyBindingError,
        RecordedTransitionAuthorityError,
        TypeError,
        ValueError,
    ) as exc:
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority lacks exact same-event Writer authority"
        ) from exc
    authority_ids = result.get("historical_family_authority_ids")
    result_binding_valid = (
        result.get("historical_family_authority_id") == authority.identity
        if event_kind == "historical_replay_satisfaction_invalidated"
        else isinstance(authority_ids, list)
        and all(type(item) is str for item in authority_ids)
        and len(authority_ids) == len(set(authority_ids))
        and authority.identity in authority_ids
    )
    if (
        record.kind != "historical-family-authority"
        or record.record_id != authority.identity
        or record.subject
        != f"ReplayObligation:{authority.replay_obligation_id}"
        or record.status != "accepted"
        or record.fingerprint
        != authority.identity.removeprefix("historical-family-authority:")
        or record.payload != authority.to_identity_payload()
        or index.get("historical-family-authority", authority.identity) != record
        or not result_binding_valid
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority lacks exact same-event Writer authority"
        )
    return authority


def require_sibling_recertification_family_core(
    index: LocalIndex | LocalIndexView,
    *,
    target_authority: HistoricalFamilyAuthority,
    source_replay_study_id: str,
) -> HistoricalFamilyAuthority:
    """Bind omitted-sibling credit to the source Study's exact family core."""

    study = index.get("study-open", source_replay_study_id)
    proposal = (
        None if study is None else study.payload.get("semantic_proposal")
    )
    source_authority_id = (
        None
        if not isinstance(proposal, Mapping)
        else proposal.get("historical_family_authority_id")
    )
    source_record = (
        None
        if not isinstance(source_authority_id, str)
        else index.get("historical-family-authority", source_authority_id)
    )
    if source_record is None:
        raise HistoricalFamilyAuthorityAdmissionError(
            "sibling recertification source family authority is absent"
        )
    source_authority = require_recorded_historical_family_authority(
        index,
        source_record,
    )
    if (
        study is None
        or study.kind != "study-open"
        or study.record_id != source_replay_study_id
        or proposal.get("historical_obligation_id")
        != source_authority.replay_obligation_id
        or proposal.get("historical_family_identity")
        != source_authority.family.identity
        or proposal.get("concurrent_family")
        != source_authority.family.manifest()
        or historical_family_core_identity(source_authority.family)
        != historical_family_core_identity(target_authority.family)
        or source_authority.reconstruction_source_path
        != target_authority.reconstruction_source_path
        or source_authority.reconstruction_source_sha256
        != target_authority.reconstruction_source_sha256
        or source_authority.reconstruction_only_parameter_names
        != target_authority.reconstruction_only_parameter_names
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "sibling recertification source and target family cores differ"
        )
    return source_authority


def prepare_historical_family_authority_record(
    *,
    repository_root: Path,
    index: LocalIndex,
    authority: HistoricalFamilyAuthority,
) -> IndexRecord:
    """Authenticate one target-specific family against immutable history."""

    if not isinstance(authority, HistoricalFamilyAuthority):
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority is not typed"
        )
    obligation_id = authority.replay_obligation_id
    relative = authority.reconstruction_source_path
    expected_prefix = "src/axiom_rift/research/"
    if (
        not relative.startswith(expected_prefix)
        or "/" in relative.removeprefix(expected_prefix)
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority source is outside the frozen registry"
        )
    source = repository_root / relative
    try:
        resolved_root = repository_root.resolve(strict=True)
        resolved_source = source.resolve(strict=True)
        resolved_source.relative_to(resolved_root)
        content = resolved_source.read_bytes()
    except (OSError, ValueError) as exc:
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority source is unavailable"
        ) from exc
    observed_sha256 = sha256(content).hexdigest()
    registered_sha256 = HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256.get(
        resolved_source.name
    )
    registered_family_identity = HISTORICAL_FAMILY_IDENTITY_BY_MODULE.get(
        resolved_source.name
    )
    registered_family_core_identity = (
        HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE.get(
            resolved_source.name
        )
    )
    if (
        source.is_symlink()
        or observed_sha256 != authority.reconstruction_source_sha256
        or registered_sha256 != observed_sha256
        or (
            registered_family_identity != authority.family.identity
            and registered_family_core_identity
            != historical_family_core_identity(authority.family)
        )
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority source differs from frozen history"
        )
    initial = index.get("historical-replay-obligation", obligation_id)
    raw_obligation = (
        None if initial is None else initial.payload.get("obligation")
    )
    try:
        obligation = historical_replay_obligation_from_identity_payload(
            raw_obligation
        )
    except (TypeError, ValueError) as exc:
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority obligation is malformed"
        ) from exc
    family = authority.family
    batch = index.get("batch-open", family.original_batch_id)
    study = index.get("study-open", family.original_study_id)
    batch_spec = None if batch is None else batch.payload.get("spec")
    batch_digest = (
        None
        if not isinstance(batch_spec, Mapping)
        else canonical_digest(domain="batch-spec", payload=dict(batch_spec))
    )
    stream = f"batch-trials:{family.original_batch_id}"
    head = index.event_head(stream)
    if (
        initial is None
        or obligation.identity != obligation_id
        or (
            family.original_study_id != obligation.original_study_id
            and family.target_historical_executable_id
            != obligation.original_executable_id
        )
        or family.target_historical_executable_id
        != obligation.original_executable_id
        or batch is None
        or batch.kind != "batch-open"
        or batch.record_id != family.original_batch_id
        or batch.subject != f"Study:{family.original_study_id}"
        or batch.status != "open"
        or batch_digest is None
        or batch.record_id != f"batch:{batch_digest}"
        or batch.fingerprint != batch_digest
        or batch.payload.get("batch_hash") != batch_digest
        or batch_spec.get("max_trials") != family.family_size
        or study is None
        or study.kind != "study-open"
        or study.record_id != family.original_study_id
        or study.subject != f"Study:{family.original_study_id}"
        or batch_spec.get("study_hash") != study.fingerprint
        or head is None
        or head.sequence != family.family_size
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority differs from obligation history"
        )
    _require_cross_study_family_evidence_bridge(
        repository_root=repository_root,
        index=index,
        obligation=obligation,
        authority=authority,
    )
    for ordinal, member in enumerate(family.members, start=1):
        trial = index.event_record(stream, ordinal)
        executable = None if trial is None else trial.payload.get("executable")
        executable_parameters = (
            None
            if not isinstance(executable, Mapping)
            else executable.get("parameters")
        )
        expected_parameters = member.parameter_values()
        missing_parameters = (
            set()
            if not isinstance(executable_parameters, Mapping)
            else set(expected_parameters).difference(executable_parameters)
        )
        if (
            trial is None
            or trial.kind != "trial"
            or trial.status != "evaluated"
            or trial.record_id != member.historical_reference_executable_id
            or trial.subject != f"Batch:{family.original_batch_id}"
            or trial.event_stream != stream
            or trial.event_sequence != ordinal
            or trial.payload.get("study_id") != family.original_study_id
            or not isinstance(executable, Mapping)
            or trial.record_id
            != "executable:"
            + canonical_digest(domain="executable", payload=dict(executable))
            or trial.fingerprint
            != trial.record_id.removeprefix("executable:")
            or not isinstance(executable_parameters, Mapping)
            or missing_parameters
            != set(authority.reconstruction_only_parameter_names)
            or any(
                executable_parameters.get(name) != value
                for name, value in expected_parameters.items()
                if name not in missing_parameters
            )
        ):
            raise HistoricalFamilyAuthorityAdmissionError(
                "historical family authority member order differs from history"
            )
    final_trial = index.event_record(stream, family.family_size)
    if (
        final_trial is None
        or final_trial.record_id != head.record_id
        or final_trial.fingerprint != head.fingerprint
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority trial head is inconsistent"
        )
    if index.get("historical-family-authority", authority.identity) is not None:
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority identity already exists"
        )
    if index.records_by_subject_status(
        f"ReplayObligation:{obligation_id}",
        "accepted",
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "replay obligation already has accepted family authority"
        )
    return IndexRecord(
        kind="historical-family-authority",
        record_id=authority.identity,
        subject=f"ReplayObligation:{obligation_id}",
        status="accepted",
        fingerprint=authority.identity.removeprefix(
            "historical-family-authority:"
        ),
        payload=authority.to_identity_payload(),
    )


__all__ = [
    "HistoricalFamilyAuthorityAdmissionError",
    "prepare_historical_family_authority_record",
    "require_recorded_historical_family_authority",
    "require_sibling_recertification_family_core",
]
