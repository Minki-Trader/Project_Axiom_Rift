"""Read-only durable projection adapter for current Portfolio axis status.

Portfolio snapshots stay immutable.  This module joins later source
invalidations, historical replay streams, and audit-only evidence-scope
overlays to the exact Executable/Study/axis lineage they affect.  A malformed
or ambiguous join fails closed instead of silently blocking or freeing the
wrong branch of the research forest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.component_surface import (
    ComponentManifestError,
    component_spec_from_manifest,
)
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.evidence_scope_projection import (
    EvidenceScopeProjectionError,
    effective_completion_evidence_scope,
)
from axiom_rift.operations.historical_cost_semantics_common import (
    COMPLETION_SCOPE_RECORD_KIND,
)
from axiom_rift.operations.historical_cost_semantics_reader import (
    HistoricalCostSemanticsProjectionError,
    effective_historical_completion_cost_authority,
)
from axiom_rift.operations.replay_projection import (
    ReplayAuthorityError,
    ReplayProjectionError,
    obligation_heads,
    require_recorded_satisfaction,
    require_satisfaction_invalidation_record,
)
from axiom_rift.research.effective_axis import (
    EffectiveAxisResolution,
    EvidenceScopeAxisBinding,
    HistoricalCostAxisBinding,
    ReplayAxisBinding,
    SourceInvalidationBinding,
    SourceReplacementBinding,
    resolve_effective_axis,
)
from axiom_rift.research.effective_evidence_scope import (
    EvidenceScopeError,
    HistoricalEvidenceScopeOverlay,
    historical_evidence_scope_from_payload,
)
from axiom_rift.research.replay_obligation import (
    HistoricalReplayObligation,
    ReplayDeferral,
    ReplayExecutionBinding,
    ReplayObligationStatus,
    ReplayResolutionScope,
    ReplaySatisfaction,
    historical_replay_obligation_from_identity_payload,
    replay_deferral_from_identity_payload,
)
from axiom_rift.research.source_authority import (
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
    SourceReplacementLineage,
)
from axiom_rift.research.sources import (
    SourceContract,
    SourceEligibilityReceipt,
    SourceEligibilityState,
    SourceTransitionEvidence,
    SourceType,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class EffectiveAxisProjectionError(RuntimeError):
    """Durable axis, replay, scope, or source authority is malformed."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EffectiveAxisProjectionError(f"{name} must be non-empty ASCII")
    return value


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(prefix)
    if text == digest or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise EffectiveAxisProjectionError(f"{name} must use {prefix}<sha256>")
    return text


def _canonical_source_ids(name: str, value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(type(source_id) is not str for source_id in value)
        or value != sorted(set(value))
    ):
        raise EffectiveAxisProjectionError(
            f"{name} must be a sorted unique source identity list"
        )
    return tuple(
        _identity(name, source_id, "source:") for source_id in value
    )


def eligible_performance_source_ids(
    executable: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return only sources authorized for performance use by an Executable.

    ``source_contracts`` remains the exact performance/SourcePermit surface.
    It must not be widened merely because an eligibility-only chassis audits a
    SourceContract without using it in a performance Batch.
    """

    if not isinstance(executable, Mapping):
        raise EffectiveAxisProjectionError("Executable source payload is malformed")
    return _canonical_source_ids(
        "Executable performance source contracts",
        executable.get("source_contracts"),
    )


def source_authority_subject_ids(
    executable: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive every SourceContract whose authority governs an Executable.

    Performance sources are the top-level ``source_contracts`` set.  A typed
    ``external_source.*`` component additionally names an authority subject in
    ``spec.source_contract_id`` even when the Executable is an eligibility-only
    no-trade audit and therefore has no performance source.  Current typed
    manifests, semantic source dependencies, and ``performance_allowed``
    declarations are reconstructed and cross-checked; legacy fixture payloads
    retain their exact top-level meaning without gaining inferred authority.
    """

    performance_sources = eligible_performance_source_ids(executable)
    if executable.get("schema") != "executable_spec.v1":
        return performance_sources

    component_ids = executable.get("component_identities")
    manifests = executable.get("component_manifests")
    if (
        not isinstance(component_ids, list)
        or not component_ids
        or any(type(component_id) is not str for component_id in component_ids)
        or not isinstance(manifests, list)
        or len(component_ids) != len(manifests)
        or len(component_ids) != len(set(component_ids))
    ):
        raise EffectiveAxisProjectionError(
            "typed Executable component authority is malformed"
        )

    authority_subjects = set(performance_sources)
    semantic_source_dependencies: set[str] = set()
    typed_external_sources: dict[str, bool] = {}
    for component_id, manifest in zip(component_ids, manifests, strict=True):
        try:
            component = component_spec_from_manifest(manifest)
        except ComponentManifestError as exc:
            raise EffectiveAxisProjectionError(
                "typed Executable component manifest is malformed"
            ) from exc
        if component.identity != component_id:
            raise EffectiveAxisProjectionError(
                "typed Executable component identity differs from its manifest"
            )
        component_sources = tuple(
            dependency
            for dependency in component.semantic_dependencies
            if dependency.startswith("source:")
        )
        for source_id in component_sources:
            _identity(
                "component semantic source dependency",
                source_id,
                "source:",
            )
        semantic_source_dependencies.update(component_sources)

        specification = component.specification()
        if component.protocol.startswith("external_source."):
            if not isinstance(specification, Mapping):
                raise EffectiveAxisProjectionError(
                    "typed external_source component specification is malformed"
                )
            if "source_contract_id" not in specification:
                if component_sources:
                    raise EffectiveAxisProjectionError(
                        "typed external_source semantic source dependency lacks a source_contract_id"
                    )
                continue
            source_id = _identity(
                "typed external_source authority subject",
                specification.get("source_contract_id"),
                "source:",
            )
            if component_sources not in {(), (source_id,)}:
                raise EffectiveAxisProjectionError(
                    "typed external_source component disagrees with its semantic source dependency"
                )
            if not component_sources and (
                specification.get("performance_allowed") is not False
            ):
                raise EffectiveAxisProjectionError(
                    "eligibility-only external_source authority requires explicit performance_allowed false"
                )
            if (
                component_sources
                and "performance_allowed" in specification
                and specification.get("performance_allowed") is not True
            ):
                raise EffectiveAxisProjectionError(
                    "performance external_source authority cannot declare performance_allowed false"
                )
            if source_id in typed_external_sources and (
                typed_external_sources[source_id] != bool(component_sources)
            ):
                raise EffectiveAxisProjectionError(
                    "typed external_source authority has conflicting performance semantics"
                )
            typed_external_sources[source_id] = bool(component_sources)
            authority_subjects.add(source_id)
        elif isinstance(specification, Mapping) and "source_contract_id" in specification:
            raise EffectiveAxisProjectionError(
                "source_contract_id requires a typed external_source component"
            )

    if semantic_source_dependencies != set(performance_sources):
        raise EffectiveAxisProjectionError(
            "Executable performance sources differ from component semantic dependencies"
        )
    if any(
        source_id in performance_sources and not participates_in_performance
        for source_id, participates_in_performance in typed_external_sources.items()
    ):
        raise EffectiveAxisProjectionError(
            "typed external_source performance authority lacks its semantic dependency"
        )
    return tuple(sorted(authority_subjects))


@dataclass(frozen=True, slots=True)
class _AxisLineageProjection:
    source_ids_by_axis: Mapping[str, frozenset[str]]
    executable_ids_by_axis: Mapping[str, tuple[str, ...]]


def _axis_lineage_projection(
    index: LocalIndex | LocalIndexView,
    *,
    axis_identities: Sequence[str],
) -> _AxisLineageProjection:
    """Project only named axes through allowlisted payload indexes."""

    identities = tuple(
        _identity("axis lineage identity", value, "axis:")
        for value in axis_identities
    )
    if identities != tuple(sorted(set(identities))):
        raise EffectiveAxisProjectionError(
            "axis lineage identities must be sorted and unique"
        )
    lineage: dict[str, set[str]] = {
        identity: set() for identity in identities
    }
    executable_ids: dict[str, set[str]] = {
        identity: set() for identity in identities
    }

    def register(identity: object, executable: object) -> None:
        if identity is None and executable is None:
            return
        if identity is None:
            raise EffectiveAxisProjectionError(
                "Executable source lineage lacks its axis identity"
            )
        typed_identity = _identity("axis source-lineage identity", identity, "axis:")
        if executable is None:
            return
        if not isinstance(executable, Mapping):
            raise EffectiveAxisProjectionError("axis source lineage is malformed")
        sources = source_authority_subject_ids(executable)
        lineage.setdefault(typed_identity, set()).update(sources)

    for decision in index.records_by_payload_text_values(
        "portfolio-decision",
        "target_axis_identity",
        identities,
    ):
        register(
            decision.payload.get("target_axis_identity"),
            decision.payload.get("baseline_executable"),
        )
    for study in index.records_by_payload_text_values(
        "study-open",
        "portfolio_axis_identity",
        identities,
    ):
        controlled = study.payload.get("controlled_chassis")
        baseline = (
            None
            if controlled is None
            else controlled.get("baseline_executable")
            if isinstance(controlled, Mapping)
            else controlled
        )
        register(study.payload.get("portfolio_axis_identity"), baseline)
    for trial in index.records_by_payload_text_values(
        "trial",
        "portfolio_axis_identity",
        identities,
    ):
        trial_axis_identity = _identity(
            "trial Portfolio axis identity",
            trial.payload.get("portfolio_axis_identity"),
            "axis:",
        )
        register(
            trial_axis_identity,
            trial.payload.get("executable"),
        )
        executable_ids[trial_axis_identity].add(
            _identity(
                "axis trial Executable id",
                trial.record_id,
                "executable:",
            )
        )
    return _AxisLineageProjection(
        source_ids_by_axis={
            axis_identity: frozenset(source_ids)
            for axis_identity, source_ids in lineage.items()
        },
        executable_ids_by_axis={
            axis_identity: tuple(sorted(values))
            for axis_identity, values in executable_ids.items()
        },
    )


def _axis_source_contract_ids_from_lineage(
    axis: Mapping[str, Any],
    lineage: _AxisLineageProjection,
) -> tuple[str, ...]:
    axis_identity = _identity(
        "Portfolio axis identity", axis.get("axis_identity"), "axis:"
    )
    return tuple(
        sorted(lineage.source_ids_by_axis.get(axis_identity, frozenset()))
    )


def axis_source_contract_ids(
    index: LocalIndex | LocalIndexView,
    axis: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive immutable source lineage from all durable axis executions."""

    axis_identity = _identity(
        "Portfolio axis identity", axis.get("axis_identity"), "axis:"
    )
    return _axis_source_contract_ids_from_lineage(
        axis,
        _axis_lineage_projection(
            index,
            axis_identities=(axis_identity,),
        ),
    )


def _source_contract_state(
    index: LocalIndex,
    *,
    source_id: str,
    state_record_id: str,
    eligible_required: bool,
) -> tuple[IndexRecord, SourceContract]:
    """Rebuild one canonical source state used by replacement authority."""

    _identity("source replacement SourceContract", source_id, "source:")
    record = index.get("source-state", state_record_id)
    allowed_states = {
        SourceEligibilityState.HISTORICAL_AUDITED.value,
        SourceEligibilityState.RUNTIME_ELIGIBLE.value,
    }
    if not eligible_required:
        allowed_states.add(SourceEligibilityState.CONTEXT_ONLY.value)
    contract_payload = (
        None if record is None else record.payload.get("contract")
    )
    try:
        contract = SourceContract(
            display_name="source-replacement-projection",
            canonical_instrument=contract_payload["canonical_instrument"],
            runtime_identifier=contract_payload["runtime_identifier"],
            source_type=SourceType(contract_payload["source_type"]),
            instrument_semantics=contract_payload["instrument_semantics"],
            mapping_semantics=contract_payload["mapping_semantics"],
            schema_semantics=contract_payload["schema_semantics"],
            field_semantics=contract_payload["field_semantics"],
            clock_semantics=contract_payload["clock_semantics"],
            availability_semantics=contract_payload["availability_semantics"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "source replacement SourceContract state is malformed"
        ) from exc
    sequence = None if record is None else record.event_sequence
    expected_id = (
        None
        if record is None or sequence is None
        else canonical_digest(
            domain="source-state",
            payload={
                "source_id": source_id,
                "state": record.status,
                "ordinal": sequence,
                "evidence_receipt_id": record.payload.get(
                    "evidence_receipt_id"
                ),
            },
        )
    )
    if (
        record is None
        or record.status not in allowed_states
        or record.subject != f"Source:{source_id}"
        or record.fingerprint != source_id
        or record.event_stream != f"source:{source_id}"
        or sequence is None
        or sequence < 1
        or record.payload.get("ordinal") != sequence
        or record.record_id != expected_id
        or contract.source_contract_id != source_id
        or contract.to_identity_payload() != contract_payload
        or record.payload.get("contract_hash") != source_id.removeprefix("source:")
        or record.payload.get("mapping_identity") != contract.mapping_identity
        or record.payload.get("schema_identity") != contract.schema_identity
        or record.payload.get("field_identity") != contract.field_identity
        or record.payload.get("clock_identity") != contract.clock_identity
        or record.payload.get("availability_identity")
        != contract.availability_identity
    ):
        raise EffectiveAxisProjectionError(
            "source replacement SourceContract state is not canonical"
        )
    receipt_payload = record.payload.get("receipt")
    evidence_receipt_id = record.payload.get("evidence_receipt_id")
    transition = record.payload.get("transition_evidence")
    if record.status == SourceEligibilityState.CONTEXT_ONLY.value:
        if any(
            value is not None
            for value in (receipt_payload, evidence_receipt_id, transition)
        ):
            raise EffectiveAxisProjectionError(
                "context-only source replacement state carries evidence"
            )
        return record, contract
    try:
        receipt = SourceEligibilityReceipt(
            source_contract_id=receipt_payload["source_contract_id"],
            evidence=SourceTransitionEvidence(receipt_payload["evidence"]),
            producer_completion_id=receipt_payload["producer_completion_id"],
            observed_at_utc=receipt_payload["observed_at_utc"],
            artifact_hashes=tuple(receipt_payload["artifact_hashes"]),
            facts=receipt_payload["facts"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "source replacement eligibility receipt is malformed"
        ) from exc
    legal_evidence = (
        receipt.evidence is SourceTransitionEvidence.HISTORICAL_AUDIT
        if record.status == SourceEligibilityState.HISTORICAL_AUDITED.value
        else receipt.evidence
        in {
            SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
        }
    )
    if (
        receipt.source_contract_id != source_id
        or receipt.identity != evidence_receipt_id
        or receipt.to_identity_payload() != receipt_payload
        or transition != receipt.evidence.value
        or not legal_evidence
    ):
        raise EffectiveAxisProjectionError(
            "source replacement eligibility receipt is not canonical"
        )
    return record, contract


def validate_source_replacement_lineage(
    index: LocalIndex | LocalIndexView,
    lineage: SourceReplacementLineage,
    *,
    require_current_replacement_source: bool,
) -> SourceReplacementBinding:
    """Verify the exact invalidation, source-state, and two-axis lineage."""

    if not isinstance(lineage, SourceReplacementLineage):
        raise EffectiveAxisProjectionError(
            "source replacement lineage is not typed"
        )
    snapshot = index.get("portfolio-snapshot", lineage.portfolio_snapshot_id)
    raw_axes = None if snapshot is None else snapshot.payload.get("axes")
    if (
        snapshot is None
        or snapshot.subject != f"Mission:{lineage.mission_id}"
        or not isinstance(raw_axes, list)
    ):
        raise EffectiveAxisProjectionError(
            "source replacement Portfolio snapshot is unavailable"
        )
    axes = {
        axis.get("axis_id"): axis
        for axis in raw_axes
        if isinstance(axis, Mapping) and isinstance(axis.get("axis_id"), str)
    }
    original_axis = axes.get(lineage.original_axis_id)
    replacement_axis = axes.get(lineage.replacement_axis_id)
    if (
        len(axes) != len(raw_axes)
        or original_axis is None
        or replacement_axis is None
        or original_axis.get("axis_identity") != lineage.original_axis_identity
        or replacement_axis.get("axis_identity")
        != lineage.replacement_axis_identity
        or replacement_axis.get("status") not in {"open", "preserved"}
    ):
        raise EffectiveAxisProjectionError(
            "source replacement axes are missing, stale, or not schedulable"
        )
    source_lineage = _axis_lineage_projection(
        index,
        axis_identities=tuple(
            sorted(
                {
                    lineage.original_axis_identity,
                    lineage.replacement_axis_identity,
                }
            )
        ),
    )
    original_sources = set(
        _axis_source_contract_ids_from_lineage(original_axis, source_lineage)
    )
    replacement_sources = set(
        _axis_source_contract_ids_from_lineage(replacement_axis, source_lineage)
    )
    if (
        lineage.invalidated_source_contract_id not in original_sources
        or lineage.replacement_source_contract_id not in replacement_sources
        or lineage.invalidated_source_contract_id in replacement_sources
    ):
        raise EffectiveAxisProjectionError(
            "source replacement axes lack their exact source lineage"
        )
    invalidation_record = index.get(
        "source-authority-invalidation", lineage.invalidation_id
    )
    try:
        invalidation = SourceAuthorityInvalidation.from_identity_payload(
            None
            if invalidation_record is None
            else invalidation_record.payload.get("invalidation")
        )
        manifest = SourceAuthorityAuditManifest.from_mapping(
            None
            if invalidation_record is None
            else invalidation_record.payload.get("audit_manifest")
        )
        latch = SourceAuthorityLatch.from_mapping(
            None
            if invalidation_record is None
            else invalidation_record.payload.get("latch")
        )
        invalidation.require_manifest(manifest)
        expected_latch = SourceAuthorityLatch.bind(
            invalidation=invalidation,
            manifest=manifest,
        )
    except (TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "source replacement invalidation authority is malformed"
        ) from exc
    authority_head = index.event_head(
        f"source-authority:{lineage.invalidated_source_contract_id}"
    )
    if (
        invalidation_record is None
        or invalidation_record.status != "confirmed_and_suspended"
        or invalidation_record.subject
        != f"Source:{lineage.invalidated_source_contract_id}"
        or invalidation_record.record_id != invalidation.identity
        or invalidation_record.fingerprint
        != invalidation.identity.removeprefix(
            "source-authority-invalidation:"
        )
        or invalidation.source_contract_id
        != lineage.invalidated_source_contract_id
        or invalidation.identity != lineage.invalidation_id
        or latch.to_identity_payload() != expected_latch.to_identity_payload()
        or authority_head is None
        or authority_head.record_id != invalidation_record.record_id
        or authority_head.sequence != invalidation_record.event_sequence
    ):
        raise EffectiveAxisProjectionError(
            "source replacement invalidation authority is not current"
        )
    _old_state, old_contract = _source_contract_state(
        index,
        source_id=lineage.invalidated_source_contract_id,
        state_record_id=invalidation.source_state_record_id,
        eligible_required=False,
    )
    replacement_state, replacement_contract = _source_contract_state(
        index,
        source_id=lineage.replacement_source_contract_id,
        state_record_id=lineage.replacement_source_state_record_id,
        eligible_required=True,
    )
    if (
        old_contract.canonical_instrument
        != replacement_contract.canonical_instrument
        or old_contract.source_type is not replacement_contract.source_type
    ):
        raise EffectiveAxisProjectionError(
            "replacement SourceContract changes the source subject"
        )
    replacement_authority_head = index.event_head(
        f"source-authority:{lineage.replacement_source_contract_id}"
    )
    if require_current_replacement_source:
        replacement_head = index.event_head(
            f"source:{lineage.replacement_source_contract_id}"
        )
        if (
            replacement_head is None
            or replacement_head.record_id != replacement_state.record_id
            or replacement_authority_head is not None
        ):
            raise EffectiveAxisProjectionError(
                "replacement SourceContract is not the current eligible head"
            )
    try:
        return SourceReplacementBinding(
            record_id=lineage.identity,
            mission_id=lineage.mission_id,
            original_axis_id=lineage.original_axis_id,
            original_axis_identity=lineage.original_axis_identity,
            invalidation_record_id=lineage.invalidation_id,
            invalidated_source_contract_id=(
                lineage.invalidated_source_contract_id
            ),
            replacement_source_contract_id=(
                lineage.replacement_source_contract_id
            ),
            replacement_source_state_record_id=(
                lineage.replacement_source_state_record_id
            ),
            replacement_axis_id=lineage.replacement_axis_id,
            replacement_axis_identity=lineage.replacement_axis_identity,
        )
    except ValueError as exc:
        raise EffectiveAxisProjectionError(
            "source replacement binding is malformed"
        ) from exc


@dataclass(frozen=True, slots=True)
class _ExecutableAxisLineage:
    executable_id: str
    mission_id: str
    study_id: str
    axis_id: str
    axis_identity: str


def _trial_axis_lineage(
    index: LocalIndex,
    executable_id: str,
) -> _ExecutableAxisLineage:
    executable_id = _identity("lineage Executable id", executable_id, "executable:")
    trial = index.get("trial", executable_id)
    if trial is None:
        raise EffectiveAxisProjectionError(
            "replay or evidence-scope Executable lacks its counted trial"
        )
    payload = trial.payload
    mission_id = _ascii("trial Mission id", payload.get("mission_id"))
    study_id = _ascii("trial Study id", payload.get("study_id"))
    axis_id = _ascii("trial Portfolio axis id", payload.get("portfolio_axis_id"))
    axis_identity = _identity(
        "trial Portfolio axis identity",
        payload.get("portfolio_axis_identity"),
        "axis:",
    )
    study = index.get("study-open", study_id)
    if (
        trial.record_id != executable_id
        or trial.status != "evaluated"
        or trial.fingerprint != executable_id.removeprefix("executable:")
        or study is None
        or study.status not in {"open", "closed"}
        or study.payload.get("mission_id") != mission_id
        or study.payload.get("portfolio_axis_id") != axis_id
        or study.payload.get("portfolio_axis_identity") != axis_identity
        or study.subject != f"Study:{study_id}"
    ):
        raise EffectiveAxisProjectionError(
            "Executable trial-to-Study-to-axis lineage is malformed or ambiguous"
        )
    return _ExecutableAxisLineage(
        executable_id=executable_id,
        mission_id=mission_id,
        study_id=study_id,
        axis_id=axis_id,
        axis_identity=axis_identity,
    )


def _completion_axis_lineage(
    index: LocalIndex,
    completion: IndexRecord,
) -> _ExecutableAxisLineage:
    scientific = completion.payload.get("scientific")
    executable_id = (
        None
        if not isinstance(scientific, Mapping)
        else scientific.get("executable_id")
    )
    lineage = _trial_axis_lineage(
        index,
        _identity("completion Executable id", executable_id, "executable:"),
    )
    job_id = _ascii("completion Job id", completion.payload.get("job_id"))
    declaration = index.get("job-declared", job_id)
    if (
        completion.status not in {"success", "failed", "not_evaluable"}
        or declaration is None
        or declaration.payload.get("mission_id") != lineage.mission_id
        or declaration.payload.get("study_id") != lineage.study_id
    ):
        raise EffectiveAxisProjectionError(
            "completion-to-Job-to-Executable axis lineage is malformed"
        )
    return lineage


def _obligation_axis_lineage(
    index: LocalIndex,
    obligation: HistoricalReplayObligation,
) -> _ExecutableAxisLineage:
    lineage = _trial_axis_lineage(index, obligation.original_executable_id)
    completion = index.get(
        "job-completed", obligation.original_completion_record_id
    )
    close_record = index.get(
        "study-close", obligation.original_study_close_record_id
    )
    completion_lineage = (
        None
        if completion is None
        else _completion_axis_lineage(index, completion)
    )
    if (
        lineage.study_id != obligation.original_study_id
        or completion_lineage != lineage
        or close_record is None
        or close_record.subject != f"Study:{obligation.original_study_id}"
    ):
        raise EffectiveAxisProjectionError(
            "replay obligation is not bound to its exact original Executable axis"
        )
    return lineage


def _resolve_obligation_heads(
    index: LocalIndex | LocalIndexView,
    initials: Sequence[IndexRecord],
) -> tuple[tuple[HistoricalReplayObligation, IndexRecord], ...]:
    mission_ids: set[str] = set()
    selected_ids: set[str] = set()
    values = tuple(initials)
    for initial in values:
        try:
            obligation = historical_replay_obligation_from_identity_payload(
                initial.payload.get("obligation", {})
            )
        except (TypeError, ValueError) as exc:
            raise EffectiveAxisProjectionError(
                "historical replay obligation projection is malformed"
            ) from exc
        mission_ids.add(obligation.governing_mission_id)
        selected_ids.add(obligation.identity)
    if len(selected_ids) != len(values):
        raise EffectiveAxisProjectionError(
            "historical replay obligation selection is ambiguous"
        )
    resolved: list[tuple[HistoricalReplayObligation, IndexRecord]] = []
    try:
        for mission_id in sorted(mission_ids):
            resolved.extend(
                pair
                for pair in obligation_heads(index, mission_id=mission_id)
                if pair[0].identity in selected_ids
            )
    except ReplayProjectionError as exc:
        raise EffectiveAxisProjectionError(str(exc)) from exc
    if len(resolved) != len(values) or len(
        {obligation.identity for obligation, _head in resolved}
    ) != len(resolved):
        raise EffectiveAxisProjectionError(
            "historical replay obligation Mission projection is ambiguous"
        )
    return tuple(sorted(resolved, key=lambda item: item[0].identity))


def _obligation_initials_for_executables(
    index: LocalIndex | LocalIndexView,
    executable_ids: Sequence[str],
) -> tuple[IndexRecord, ...]:
    identities = tuple(sorted(set(executable_ids)))
    for executable_id in identities:
        _identity(
            "replay lineage Executable id",
            executable_id,
            "executable:",
        )
    records: dict[str, IndexRecord] = {}
    for record in index.records_by_payload_text_values(
        "historical-replay-obligation",
        "obligation_original_executable_id",
        identities,
    ):
        prior = records.setdefault(record.record_id, record)
        if prior != record:
            raise EffectiveAxisProjectionError(
                "historical replay obligation lookup is ambiguous"
            )
    return tuple(records[key] for key in sorted(records))


def _obligation_heads_for_executables(
    index: LocalIndex | LocalIndexView,
    executable_ids: Sequence[str],
) -> tuple[tuple[HistoricalReplayObligation, IndexRecord], ...]:
    return _resolve_obligation_heads(
        index,
        _obligation_initials_for_executables(index, executable_ids),
    )


def _obligation_heads_for_mission(
    index: LocalIndex | LocalIndexView,
    mission_id: str,
) -> tuple[tuple[HistoricalReplayObligation, IndexRecord], ...]:
    _ascii("replay governing Mission id", mission_id)
    return _resolve_obligation_heads(
        index,
        index.records_by_payload_text(
            "historical-replay-obligation",
            "obligation_governing_mission_id",
            mission_id,
        ),
    )


def _completion_ids_for_executables(
    index: LocalIndex | LocalIndexView,
    executable_ids: Sequence[str],
) -> tuple[str, ...]:
    identities = tuple(sorted(set(executable_ids)))
    for executable_id in identities:
        _identity(
            "completion lineage Executable id",
            executable_id,
            "executable:",
        )
    records = index.records_by_payload_text_values(
        "job-completed",
        "scientific_executable_id",
        identities,
    )
    return tuple(sorted(record.record_id for record in records))


def _all_obligation_heads(
    index: LocalIndex | LocalIndexView,
) -> tuple[tuple[HistoricalReplayObligation, IndexRecord], ...]:
    """Explicit complete-history replay inventory, never the axis routine path."""

    return _resolve_obligation_heads(
        index,
        index.records_by_kind("historical-replay-obligation"),
    )


def _execution_binding(value: object) -> ReplayExecutionBinding:
    if not isinstance(value, Mapping):
        raise EffectiveAxisProjectionError("replay execution binding is malformed")
    try:
        binding = ReplayExecutionBinding(
            obligation_ids=tuple(value["obligation_ids"]),
            portfolio_decision_id=value["portfolio_decision_id"],
            replay_study_id=value["replay_study_id"],
            replay_executable_id=value["replay_executable_id"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "replay execution binding is malformed"
        ) from exc
    if binding.to_identity_payload() != dict(value):
        raise EffectiveAxisProjectionError("replay execution binding changed on rebuild")
    return binding


def _satisfaction(value: object) -> ReplaySatisfaction:
    if not isinstance(value, Mapping):
        raise EffectiveAxisProjectionError("replay satisfaction is malformed")
    try:
        satisfaction = ReplaySatisfaction(
            obligation_id=value["obligation_id"],
            resolution_scope=ReplayResolutionScope(value["resolution_scope"]),
            portfolio_decision_id=value["portfolio_decision_id"],
            replay_study_id=value["replay_study_id"],
            replay_executable_id=value["replay_executable_id"],
            replay_study_close_record_id=value["replay_study_close_record_id"],
            study_diagnosis_id=value["study_diagnosis_id"],
            satisfied_criterion_ids=tuple(value["satisfied_criterion_ids"]),
            evidence_record_ids=tuple(value["evidence_record_ids"]),
            remaining_scientific_condition=value.get(
                "remaining_scientific_condition"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError("replay satisfaction is malformed") from exc
    if satisfaction.to_identity_payload() != dict(value):
        raise EffectiveAxisProjectionError("replay satisfaction changed on rebuild")
    return satisfaction


def _deferral(value: object) -> ReplayDeferral:
    try:
        return replay_deferral_from_identity_payload(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError("replay deferral is malformed") from exc


@dataclass(frozen=True, slots=True)
class _OverlayAuthority:
    overlay: HistoricalEvidenceScopeOverlay
    record: IndexRecord
    completion_binding: EvidenceScopeAxisBinding


def _overlay_authorities(
    index: LocalIndex | LocalIndexView,
    *,
    known_obligation_ids: set[str],
    records: Sequence[IndexRecord],
) -> tuple[_OverlayAuthority, ...]:
    resolved: list[_OverlayAuthority] = []
    seen_completions: set[str] = set()
    for record in records:
        try:
            overlay = historical_evidence_scope_from_payload(record.payload)
        except EvidenceScopeError as exc:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope overlay is malformed"
            ) from exc
        completion = index.get("job-completed", overlay.completion_record_id)
        if completion is None:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope overlay lost its completion"
            )
        try:
            effective_scope = effective_completion_evidence_scope(index, completion)
        except EvidenceScopeProjectionError as exc:
            raise EffectiveAxisProjectionError(str(exc)) from exc
        if (
            overlay.completion_record_id in seen_completions
            or record.record_id != overlay.identity
            or effective_scope.overlay_record_id != overlay.identity
            or effective_scope.scientific_credit != 0
            or effective_scope.economic_credit != 0
            or effective_scope.terminal_credit != 0
            or set(overlay.replay_obligation_ids).difference(
                known_obligation_ids
            )
        ):
            raise EffectiveAxisProjectionError(
                "historical evidence-scope overlay binding is incomplete or ambiguous"
            )
        lineage = _completion_axis_lineage(index, completion)
        try:
            completion_binding = EvidenceScopeAxisBinding(
                axis_id=lineage.axis_id,
                axis_identity=lineage.axis_identity,
                completion_record_id=overlay.completion_record_id,
                executable_id=lineage.executable_id,
                governing_mission_id=overlay.governing_mission_id,
                overlay_record_id=overlay.identity,
                replay_obligation_ids=overlay.replay_obligation_ids,
                replay_resolution_ids=overlay.replay_resolution_ids,
            )
        except ValueError as exc:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope axis binding is malformed"
            ) from exc
        seen_completions.add(overlay.completion_record_id)
        resolved.append(
            _OverlayAuthority(
                overlay=overlay,
                record=record,
                completion_binding=completion_binding,
            )
        )
    return tuple(sorted(resolved, key=lambda item: item.overlay.identity))


def _overlay_records_for_completions(
    index: LocalIndex | LocalIndexView,
    completion_ids: Sequence[str],
) -> tuple[IndexRecord, ...]:
    identities = tuple(sorted(set(completion_ids)))
    for completion_id in identities:
        _ascii("overlay completion id", completion_id)
    records: dict[str, IndexRecord] = {}
    for record in index.records_by_payload_text_values(
        "historical-evidence-scope-overlay",
        "completion_record_id",
        identities,
    ):
        prior = records.setdefault(record.record_id, record)
        if prior != record:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope lookup is ambiguous"
            )
    return tuple(records[key] for key in sorted(records))


def _replay_axis_binding(
    *,
    index: LocalIndex,
    obligation: HistoricalReplayObligation,
    head: IndexRecord,
    lineage: _ExecutableAxisLineage,
    overlays: tuple[_OverlayAuthority, ...],
) -> ReplayAxisBinding:
    try:
        status = ReplayObligationStatus(head.status)
    except ValueError as exc:
        raise EffectiveAxisProjectionError(
            "historical replay obligation status is malformed"
        ) from exc
    if (
        head.subject != f"Mission:{obligation.governing_mission_id}"
        or head.payload.get("obligation_id")
        not in {None, obligation.identity}
    ):
        raise EffectiveAxisProjectionError(
            "historical replay obligation state binding is malformed"
        )
    resolution_scope: ReplayResolutionScope | None = None
    overlay_id: str | None = None
    if status is ReplayObligationStatus.PENDING:
        initial = (
            head.kind == "historical-replay-obligation"
            and head.record_id == obligation.identity
            and head.payload == {"obligation": obligation.to_identity_payload()}
        )
        invalidated_satisfaction = (
            head.kind == "historical-replay-satisfaction-invalidation"
        )
        if invalidated_satisfaction:
            try:
                require_satisfaction_invalidation_record(
                    index,
                    obligation=obligation,
                    record=head,
                )
            except ReplayAuthorityError as exc:
                raise EffectiveAxisProjectionError(
                    "pending replay satisfaction invalidation is malformed"
                ) from exc
        elif not initial:
            raise EffectiveAxisProjectionError(
                "pending replay obligation head is malformed"
            )
    elif status is ReplayObligationStatus.IN_PROGRESS:
        binding = _execution_binding(head.payload.get("binding"))
        expected_payload = {
            "binding": binding.to_identity_payload(),
            "obligation_id": obligation.identity,
            "prior_status": ReplayObligationStatus.PENDING.value,
        }
        expected_id = "historical-replay-progress:" + canonical_digest(
            domain="historical-replay-obligation-progress",
            payload=expected_payload,
        )
        if (
            head.kind != "historical-replay-obligation-progress"
            or binding.obligation_ids != (obligation.identity,)
            or head.payload != expected_payload
            or head.record_id != expected_id
            or head.fingerprint != binding.identity
        ):
            raise EffectiveAxisProjectionError(
                "in-progress replay obligation head is malformed"
            )
    elif status is ReplayObligationStatus.DEFERRED:
        deferral = _deferral(head.payload.get("resolution"))
        deferral_bases = tuple(
            record
            for kind in (
                "architecture-review",
                "external-blocker",
                "source-authority-invalidation",
                "study-diagnosis",
            )
            if (record := index.get(kind, deferral.basis_record_id)) is not None
        )
        if (
            head.kind != "historical-replay-obligation-resolution"
            or deferral.obligation_id != obligation.identity
            or len(deferral_bases) != 1
            or head.record_id != deferral.identity
            or head.payload
            != {
                "obligation_id": obligation.identity,
                "prior_status": head.payload.get("prior_status"),
                "resolution": deferral.to_identity_payload(),
            }
            or head.payload.get("prior_status")
            not in {
                ReplayObligationStatus.PENDING.value,
                ReplayObligationStatus.IN_PROGRESS.value,
            }
        ):
            raise EffectiveAxisProjectionError(
                "deferred replay obligation head is malformed"
            )
    else:
        satisfaction = _satisfaction(head.payload.get("resolution"))
        if (
            head.kind != "historical-replay-obligation-resolution"
            or satisfaction.obligation_id != obligation.identity
            or head.record_id != satisfaction.identity
            or head.payload
            != {
                "obligation_id": obligation.identity,
                "prior_status": head.payload.get("prior_status"),
                "resolution": satisfaction.to_identity_payload(),
            }
            or head.payload.get("prior_status")
            not in {
                ReplayObligationStatus.PENDING.value,
                ReplayObligationStatus.IN_PROGRESS.value,
            }
        ):
            raise EffectiveAxisProjectionError(
                "satisfied replay obligation head is malformed"
            )
        resolution_scope = satisfaction.resolution_scope
        try:
            require_recorded_satisfaction(
                index,
                obligation=obligation,
                satisfaction=satisfaction,
                allow_legacy_decision_binding=(
                    resolution_scope is ReplayResolutionScope.AUDIT_ONLY
                ),
                satisfaction_head=head,
            )
        except ReplayAuthorityError as exc:
            raise EffectiveAxisProjectionError(
                "satisfied replay lacks exact scientific or audit authority"
            ) from exc
        matching_overlays = tuple(
            authority
            for authority in overlays
            if obligation.identity in authority.overlay.replay_obligation_ids
            and satisfaction.identity in authority.overlay.replay_resolution_ids
        )
        if resolution_scope is ReplayResolutionScope.AUDIT_ONLY:
            if len(matching_overlays) != 1:
                raise EffectiveAxisProjectionError(
                    "audit-only replay lacks one exact evidence-scope overlay"
                )
            overlay_id = matching_overlays[0].overlay.identity
        elif matching_overlays:
            raise EffectiveAxisProjectionError(
                "scientific replay is incorrectly bound to an audit-only overlay"
            )
    try:
        return ReplayAxisBinding(
            axis_id=lineage.axis_id,
            axis_identity=lineage.axis_identity,
            governing_mission_id=obligation.governing_mission_id,
            obligation_id=obligation.identity,
            original_executable_id=obligation.original_executable_id,
            original_study_id=obligation.original_study_id,
            state_record_id=head.record_id,
            status=status,
            resolution_scope=resolution_scope,
            evidence_scope_overlay_id=overlay_id,
        )
    except ValueError as exc:
        raise EffectiveAxisProjectionError(
            "historical replay axis binding is malformed"
        ) from exc


@dataclass(frozen=True, slots=True)
class _EffectiveAuthorityIndex:
    replay_by_axis: Mapping[str, tuple[ReplayAxisBinding, ...]]
    scope_by_axis: Mapping[str, tuple[EvidenceScopeAxisBinding, ...]]
    source_replacements_by_axis: Mapping[
        str, tuple[SourceReplacementBinding, ...]
    ]
    historical_cost_by_axis: Mapping[
        str, tuple[HistoricalCostAxisBinding, ...]
    ]
    replay_bindings: tuple[ReplayAxisBinding, ...]
    scope_bindings: tuple[EvidenceScopeAxisBinding, ...]
    source_replacement_bindings: tuple[SourceReplacementBinding, ...]
    historical_cost_bindings: tuple[HistoricalCostAxisBinding, ...]


def _historical_cost_axis_bindings(
    index: LocalIndex | LocalIndexView,
    completion_ids: Sequence[str],
) -> tuple[HistoricalCostAxisBinding, ...]:
    """Resolve only the named completion keys through current latch authority."""

    resolved: list[HistoricalCostAxisBinding] = []
    for completion_id in sorted(set(completion_ids)):
        try:
            authority = effective_historical_completion_cost_authority(
                index,
                completion_id,
            )
        except HistoricalCostSemanticsProjectionError as exc:
            raise EffectiveAxisProjectionError(str(exc)) from exc
        if authority is None or not authority.scientific:
            continue
        completion = index.get("job-completed", completion_id)
        if completion is None:
            raise EffectiveAxisProjectionError(
                "historical cost authority lost its completion"
            )
        lineage = _completion_axis_lineage(index, completion)
        if lineage.executable_id != authority.executable_id:
            raise EffectiveAxisProjectionError(
                "historical cost authority differs from axis lineage"
            )
        try:
            resolved.append(
                HistoricalCostAxisBinding(
                    axis_id=lineage.axis_id,
                    axis_identity=lineage.axis_identity,
                    completion_record_id=authority.completion_record_id,
                    executable_id=authority.executable_id,
                    latch_record_id=authority.latch_record_id,
                    semantic_class=authority.semantic_class.value,
                    negative_memory_ids=authority.negative_memory_ids,
                    preserved_independent_scopes=(
                        authority.preserved_independent_scopes
                    ),
                )
            )
        except ValueError as exc:
            raise EffectiveAxisProjectionError(
                "historical cost axis binding is malformed"
            ) from exc
    return tuple(sorted(resolved, key=lambda item: item.completion_record_id))


def _source_replacement_bindings(
    index: LocalIndex | LocalIndexView,
    *,
    axis_identities: Sequence[str] | None,
) -> tuple[SourceReplacementBinding, ...]:
    resolved: list[SourceReplacementBinding] = []
    seen_streams: set[str] = set()
    if axis_identities is None:
        records = index.records_by_kind("source-replacement-lineage")
    else:
        identities = tuple(sorted(set(axis_identities)))
        for axis_identity in identities:
            _identity(
                "source replacement original axis identity",
                axis_identity,
                "axis:",
            )
        records = index.records_by_payload_text_values(
            "source-replacement-lineage",
            "lineage_original_axis_identity",
            identities,
        )
    for record in records:
        try:
            lineage = SourceReplacementLineage.from_mapping(
                record.payload.get("lineage")
            )
            binding = validate_source_replacement_lineage(
                index,
                lineage,
                require_current_replacement_source=False,
            )
        except (TypeError, ValueError) as exc:
            raise EffectiveAxisProjectionError(
                "source replacement lineage projection is malformed"
            ) from exc
        expected_stream = (
            f"source-replacement:{lineage.mission_id}:"
            f"{lineage.original_axis_identity}:"
            f"{lineage.invalidated_source_contract_id}"
        )
        head = index.event_head(expected_stream)
        expected_payload = {
            "candidate_delta": 0,
            "claim_delta": "none",
            "holdout_delta": 0,
            "lineage": lineage.to_identity_payload(),
            "scientific_credit": 0,
            "terminal_scientific_credit": 0,
            "trial_delta": 0,
        }
        if (
            expected_stream in seen_streams
            or record.record_id != lineage.identity
            or binding.record_id != lineage.identity
            or record.subject != f"Axis:{lineage.original_axis_identity}"
            or record.status != "retired_original_axis"
            or record.fingerprint
            != lineage.identity.removeprefix("source-replacement-lineage:")
            or record.payload != expected_payload
            or record.event_stream != expected_stream
            or record.event_sequence != 1
            or head is None
            or head.sequence != 1
            or head.record_id != record.record_id
            or head.record_kind != record.kind
        ):
            raise EffectiveAxisProjectionError(
                "source replacement lineage record is not canonical"
            )
        seen_streams.add(expected_stream)
        resolved.append(binding)
    return tuple(
        sorted(
            resolved,
            key=lambda item: (
                item.original_axis_identity,
                item.invalidated_source_contract_id,
            ),
        )
    )


def _effective_authority_index(
    index: LocalIndex | LocalIndexView,
    *,
    heads: Sequence[tuple[HistoricalReplayObligation, IndexRecord]],
    scope_completion_ids: Sequence[str],
    source_replacement_axis_identities: Sequence[str] | None,
) -> _EffectiveAuthorityIndex:
    """Project a keyed authority closure without reader-attached cache state."""

    heads_by_id = {
        obligation.identity: (obligation, head)
        for obligation, head in heads
    }
    if len(heads_by_id) != len(tuple(heads)):
        raise EffectiveAxisProjectionError(
            "historical replay head selection is ambiguous"
        )
    overlay_records: dict[str, IndexRecord] = {}
    while True:
        completion_ids: set[str] = set(scope_completion_ids).union(
            obligation.original_completion_record_id
            for obligation, _head in heads_by_id.values()
        )
        for _obligation, head in heads_by_id.values():
            resolution = head.payload.get("resolution")
            evidence_ids = (
                None
                if not isinstance(resolution, Mapping)
                else resolution.get("evidence_record_ids")
            )
            if isinstance(evidence_ids, list):
                completion_ids.update(
                    value for value in evidence_ids if type(value) is str
                )
        for record in _overlay_records_for_completions(index, completion_ids):
            overlay_records[record.record_id] = record
        referenced_ids: set[str] = set()
        for record in overlay_records.values():
            try:
                overlay = historical_evidence_scope_from_payload(record.payload)
            except EvidenceScopeError as exc:
                raise EffectiveAxisProjectionError(
                    "historical evidence-scope overlay is malformed"
                ) from exc
            referenced_ids.update(overlay.replay_obligation_ids)
        missing_ids = referenced_ids.difference(heads_by_id)
        if not missing_ids:
            break
        missing_initials = []
        for obligation_id in sorted(missing_ids):
            initial = index.get("historical-replay-obligation", obligation_id)
            if initial is None:
                raise EffectiveAxisProjectionError(
                    "historical evidence-scope overlay references a missing obligation"
                )
            missing_initials.append(initial)
        for obligation, head in _resolve_obligation_heads(
            index,
            missing_initials,
        ):
            heads_by_id[obligation.identity] = (obligation, head)

    resolved_heads = tuple(
        heads_by_id[key] for key in sorted(heads_by_id)
    )
    obligation_ids = set(heads_by_id)
    overlays = _overlay_authorities(
        index,
        known_obligation_ids=obligation_ids,
        records=tuple(
            overlay_records[key] for key in sorted(overlay_records)
        ),
    )
    replay_bindings = tuple(
        _replay_axis_binding(
            index=index,
            obligation=obligation,
            head=head,
            lineage=_obligation_axis_lineage(index, obligation),
            overlays=overlays,
        )
        for obligation, head in resolved_heads
    )
    replay_by_id = {binding.obligation_id: binding for binding in replay_bindings}
    for authority in overlays:
        if any(
            obligation_id not in replay_by_id
            or replay_by_id[obligation_id].status
            is not ReplayObligationStatus.SATISFIED
            or replay_by_id[obligation_id].resolution_scope
            is not ReplayResolutionScope.AUDIT_ONLY
            or replay_by_id[obligation_id].evidence_scope_overlay_id
            != authority.overlay.identity
            for obligation_id in authority.overlay.replay_obligation_ids
        ):
            raise EffectiveAxisProjectionError(
                "audit-only evidence-scope overlay lacks current replay authority"
            )
    scope_bindings = tuple(
        authority.completion_binding for authority in overlays
    )
    source_replacement_bindings = _source_replacement_bindings(
        index,
        axis_identities=source_replacement_axis_identities,
    )
    historical_cost_bindings = _historical_cost_axis_bindings(
        index,
        scope_completion_ids,
    )
    replay_by_axis: dict[str, list[ReplayAxisBinding]] = {}
    for binding in replay_bindings:
        replay_by_axis.setdefault(binding.axis_identity, []).append(binding)
    scope_by_axis: dict[str, list[EvidenceScopeAxisBinding]] = {}
    for binding in scope_bindings:
        scope_by_axis.setdefault(binding.axis_identity, []).append(binding)
    source_replacements_by_axis: dict[str, list[SourceReplacementBinding]] = {}
    for binding in source_replacement_bindings:
        source_replacements_by_axis.setdefault(
            binding.original_axis_identity, []
        ).append(binding)
    historical_cost_by_axis: dict[str, list[HistoricalCostAxisBinding]] = {}
    for binding in historical_cost_bindings:
        historical_cost_by_axis.setdefault(binding.axis_identity, []).append(
            binding
        )
    authority_index = _EffectiveAuthorityIndex(
        replay_by_axis={
            axis_identity: tuple(
                sorted(values, key=lambda item: item.obligation_id)
            )
            for axis_identity, values in replay_by_axis.items()
        },
        scope_by_axis={
            axis_identity: tuple(
                sorted(values, key=lambda item: item.overlay_record_id)
            )
            for axis_identity, values in scope_by_axis.items()
        },
        source_replacements_by_axis={
            axis_identity: tuple(
                sorted(
                    values,
                    key=lambda item: item.invalidated_source_contract_id,
                )
            )
            for axis_identity, values in source_replacements_by_axis.items()
        },
        historical_cost_by_axis={
            axis_identity: tuple(
                sorted(values, key=lambda item: item.completion_record_id)
            )
            for axis_identity, values in historical_cost_by_axis.items()
        },
        replay_bindings=replay_bindings,
        scope_bindings=scope_bindings,
        source_replacement_bindings=source_replacement_bindings,
        historical_cost_bindings=historical_cost_bindings,
    )
    return authority_index


def effective_replay_axis_bindings(
    index: LocalIndex | LocalIndexView,
    *,
    mission_id: str | None = None,
) -> tuple[ReplayAxisBinding, ...]:
    """Return immutable replay-to-original-axis bindings, optionally by Mission."""

    heads = (
        _all_obligation_heads(index)
        if mission_id is None
        else _obligation_heads_for_mission(index, mission_id)
    )
    bindings = _effective_authority_index(
        index,
        heads=heads,
        scope_completion_ids=(),
        source_replacement_axis_identities=(),
    ).replay_bindings
    return tuple(
        binding
        for binding in bindings
        if mission_id is None or binding.governing_mission_id == mission_id
    )


def mission_effective_axis_blockers(
    index: LocalIndex | LocalIndexView,
    *,
    mission_id: str,
) -> tuple[ReplayAxisBinding, ...]:
    """Return unresolved replay facts that currently forbid a Mission terminal.

    A satisfied audit-only replay completes its exact audit obligation, while
    its evidence-scope overlay removes credit only from the bound completion.
    It therefore does not block or exclude the causal axis.  A historical
    pruned axis with that remainder is projected as requiring explicit reopen.
    """

    authority = _effective_authority_index(
        index,
        heads=_obligation_heads_for_mission(index, mission_id),
        scope_completion_ids=(),
        source_replacement_axis_identities=(),
    )
    replay = tuple(
        binding
        for binding in authority.replay_bindings
        if binding.governing_mission_id == mission_id and binding.blocks_terminal
    )
    return replay


def _effective_axis_resolution_from_projection(
    index: LocalIndex | LocalIndexView,
    axis: Mapping[str, Any],
    *,
    prospective_source_ids: Sequence[str],
    source_lineage: _AxisLineageProjection,
    authority: _EffectiveAuthorityIndex,
) -> EffectiveAxisResolution:
    axis_identity = _identity(
        "Portfolio axis identity", axis.get("axis_identity"), "axis:"
    )
    sources = tuple(
        sorted(
            set(
                _axis_source_contract_ids_from_lineage(axis, source_lineage)
            ).union(prospective_source_ids)
        )
    )
    invalidations = []
    for source_id in sources:
        _identity("axis source contract", source_id, "source:")
        head = index.event_head(f"source-authority:{source_id}")
        if head is None:
            continue
        record = index.get(head.record_kind, head.record_id)
        try:
            invalidation = SourceAuthorityInvalidation.from_identity_payload(
                record.payload.get("invalidation") if record is not None else None
            )
            manifest = SourceAuthorityAuditManifest.from_mapping(
                record.payload.get("audit_manifest") if record is not None else None
            )
            latch = SourceAuthorityLatch.from_mapping(
                record.payload.get("latch") if record is not None else None
            )
            invalidation.require_manifest(manifest)
            expected_latch = SourceAuthorityLatch.bind(
                invalidation=invalidation,
                manifest=manifest,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EffectiveAxisProjectionError(
                "axis source-authority invalidation payload is malformed"
            ) from exc
        if (
            head.sequence != 1
            or record is None
            or record.kind != "source-authority-invalidation"
            or record.status != "confirmed_and_suspended"
            or record.subject != f"Source:{source_id}"
            or record.event_stream != f"source-authority:{source_id}"
            or record.event_sequence != head.sequence
            or record.record_id != invalidation.identity
            or record.fingerprint
            != invalidation.identity.removeprefix(
                "source-authority-invalidation:"
            )
            or invalidation.source_contract_id != source_id
            or record.payload.get("eligible_source_state_record_id")
            != invalidation.source_state_record_id
            or latch.to_identity_payload() != expected_latch.to_identity_payload()
            or record.payload.get("scientific_trial_delta") != 0
        ):
            raise EffectiveAxisProjectionError(
                "axis source-authority invalidation projection is malformed"
            )
        try:
            invalidations.append(
                SourceInvalidationBinding(
                    source_contract_id=source_id,
                    invalidation_record_id=record.record_id,
                )
            )
        except ValueError as exc:
            raise EffectiveAxisProjectionError(
                "axis source-authority identity is malformed"
            ) from exc
    try:
        return resolve_effective_axis(
            axis_id=axis["axis_id"],
            axis_identity=axis_identity,
            snapshot_status=axis["status"],
            source_contract_ids=sources,
            invalidations=tuple(invalidations),
            source_replacements=authority.source_replacements_by_axis.get(
                axis_identity, ()
            ),
            replay_bindings=authority.replay_by_axis.get(axis_identity, ()),
            evidence_scope_bindings=authority.scope_by_axis.get(
                axis_identity, ()
            ),
            historical_cost_bindings=authority.historical_cost_by_axis.get(
                axis_identity, ()
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "effective Portfolio axis cannot be resolved"
        ) from exc


def effective_axis_resolution(
    index: LocalIndex | LocalIndexView,
    axis: Mapping[str, Any],
    *,
    prospective_source_ids: Sequence[str] = (),
) -> EffectiveAxisResolution:
    """Resolve one axis from a fresh, reader-pure authority projection."""

    axis_identity = _identity(
        "Portfolio axis identity", axis.get("axis_identity"), "axis:"
    )
    source_lineage = _axis_lineage_projection(
        index,
        axis_identities=(axis_identity,),
    )
    return _effective_axis_resolution_from_projection(
        index,
        axis,
        prospective_source_ids=prospective_source_ids,
        source_lineage=source_lineage,
        authority=_effective_authority_index(
            index,
            heads=_obligation_heads_for_executables(
                index,
                source_lineage.executable_ids_by_axis.get(
                    axis_identity,
                    (),
                ),
            ),
            scope_completion_ids=_completion_ids_for_executables(
                index,
                source_lineage.executable_ids_by_axis.get(
                    axis_identity,
                    (),
                ),
            ),
            source_replacement_axis_identities=(axis_identity,),
        ),
    )


def effective_axis_resolutions(
    index: LocalIndex | LocalIndexView,
    axes: Sequence[Mapping[str, Any]],
    *,
    prospective_source_ids_by_axis: Mapping[str, Sequence[str]] | None = None,
) -> tuple[EffectiveAxisResolution, ...]:
    """Resolve an axis inventory with one explicit local projection memo.

    The memo lives only for this call.  It is never attached to the index or
    retained globally, so replacing a stable-head index cannot expose stale
    authority while a forest-sized scheduler avoids repeated history scans.
    """

    values = tuple(axes)
    if any(not isinstance(axis, Mapping) for axis in values):
        raise EffectiveAxisProjectionError(
            "Portfolio scheduler axes must be mappings"
        )
    axis_ids = tuple(
        _ascii("Portfolio scheduler axis id", axis.get("axis_id"))
        for axis in values
    )
    if len(axis_ids) != len(set(axis_ids)):
        raise EffectiveAxisProjectionError(
            "Portfolio scheduler axis ids are ambiguous"
        )
    prospective = (
        {} if prospective_source_ids_by_axis is None else prospective_source_ids_by_axis
    )
    if not isinstance(prospective, Mapping) or any(
        type(axis_id) is not str for axis_id in prospective
    ):
        raise EffectiveAxisProjectionError(
            "prospective source inventory must be keyed by axis id"
        )
    unknown = set(prospective).difference(axis_ids)
    if unknown:
        raise EffectiveAxisProjectionError(
            "prospective source inventory names an unknown axis"
        )
    normalized_prospective: dict[str, tuple[str, ...]] = {}
    for axis_id, source_ids in prospective.items():
        if isinstance(source_ids, (str, bytes)) or not isinstance(
            source_ids, Sequence
        ):
            raise EffectiveAxisProjectionError(
                "prospective source ids must be a sequence"
            )
        normalized_prospective[axis_id] = tuple(source_ids)
    if not values:
        return ()
    axis_identities = tuple(
        sorted(
            {
                _identity(
                    "Portfolio scheduler axis identity",
                    axis.get("axis_identity"),
                    "axis:",
                )
                for axis in values
            }
        )
    )
    source_lineage = _axis_lineage_projection(
        index,
        axis_identities=axis_identities,
    )
    executable_ids = tuple(
        sorted(
            {
                executable_id
                for values_by_axis in source_lineage.executable_ids_by_axis.values()
                for executable_id in values_by_axis
            }
        )
    )
    authority = _effective_authority_index(
        index,
        heads=_obligation_heads_for_executables(index, executable_ids),
        scope_completion_ids=_completion_ids_for_executables(
            index,
            executable_ids,
        ),
        source_replacement_axis_identities=axis_identities,
    )
    return tuple(
        _effective_axis_resolution_from_projection(
            index,
            axis,
            prospective_source_ids=normalized_prospective.get(axis_id, ()),
            source_lineage=source_lineage,
            authority=authority,
        )
        for axis_id, axis in zip(axis_ids, values, strict=True)
    )


def selectable_axis_ids(
    index: LocalIndex | LocalIndexView,
    axes: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Resolve a scheduler set without allowing one blocked axis to hide peers."""

    resolutions = effective_axis_resolutions(index, axes)
    axis_ids = tuple(item.axis_id for item in resolutions)
    if len(axis_ids) != len(set(axis_ids)):
        raise EffectiveAxisProjectionError("Portfolio scheduler axis ids are ambiguous")
    return tuple(sorted(item.axis_id for item in resolutions if item.selectable))


def audit_effective_axis_projection(
    index: LocalIndex | LocalIndexView,
) -> dict[str, int]:
    """Run the explicit complete-history integrity audit outside routine reads."""

    axis_identities: set[str] = set()
    for kind, identity_field, executable_field in (
        ("portfolio-decision", "target_axis_identity", "baseline_executable"),
        ("study-open", "portfolio_axis_identity", "controlled_chassis"),
        ("trial", "portfolio_axis_identity", "executable"),
    ):
        for record in index.records_by_kind(kind):
            identity = record.payload.get(identity_field)
            executable = record.payload.get(executable_field)
            if identity is None and executable is None:
                continue
            if identity is None:
                raise EffectiveAxisProjectionError(
                    "Executable source lineage lacks its axis identity"
                )
            axis_identities.add(
                _identity("full-audit axis identity", identity, "axis:")
            )
    lineage = _axis_lineage_projection(
        index,
        axis_identities=tuple(sorted(axis_identities)),
    ) if axis_identities else _AxisLineageProjection(
        source_ids_by_axis={},
        executable_ids_by_axis={},
    )
    overlay_records = index.records_by_kind(
        "historical-evidence-scope-overlay"
    )
    overlay_completion_ids: list[str] = []
    for record in overlay_records:
        try:
            overlay = historical_evidence_scope_from_payload(record.payload)
        except EvidenceScopeError as exc:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope overlay is malformed"
            ) from exc
        overlay_completion_ids.append(overlay.completion_record_id)
    cost_records = index.records_by_kind(COMPLETION_SCOPE_RECORD_KIND)
    cost_completion_ids = tuple(
        sorted(record.record_id for record in cost_records)
    )
    authority = _effective_authority_index(
        index,
        heads=_all_obligation_heads(index),
        scope_completion_ids=tuple(
            sorted(set(overlay_completion_ids).union(cost_completion_ids))
        ),
        source_replacement_axis_identities=None,
    )
    if {
        binding.overlay_record_id for binding in authority.scope_bindings
    } != {record.record_id for record in overlay_records}:
        raise EffectiveAxisProjectionError(
            "complete evidence-scope overlay inventory is not authoritative"
        )
    projected_scientific_cost_ids = {
        record.record_id
        for record in cost_records
        if record.status == "qualified"
    }
    if {
        binding.completion_record_id
        for binding in authority.historical_cost_bindings
    } != projected_scientific_cost_ids:
        raise EffectiveAxisProjectionError(
            "complete historical cost axis inventory is not authoritative"
        )
    return {
        "axis_count": len(lineage.source_ids_by_axis),
        "replay_binding_count": len(authority.replay_bindings),
        "scope_binding_count": len(authority.scope_bindings),
        "source_replacement_binding_count": len(
            authority.source_replacement_bindings
        ),
        "historical_cost_binding_count": len(
            authority.historical_cost_bindings
        ),
    }


__all__ = [
    "EffectiveAxisProjectionError",
    "audit_effective_axis_projection",
    "axis_source_contract_ids",
    "eligible_performance_source_ids",
    "effective_axis_resolution",
    "effective_axis_resolutions",
    "effective_replay_axis_bindings",
    "mission_effective_axis_blockers",
    "selectable_axis_ids",
    "source_authority_subject_ids",
    "validate_source_replacement_lineage",
]
