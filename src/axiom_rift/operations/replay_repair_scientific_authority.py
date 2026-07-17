"""Scientific authority required to promote a repaired replay implementation.

The implementation Repair itself is engineering evidence.  A family-wide
successor admission may use it only after the repaired Job's original
scientific binding, production semantic-equivalence proof, completion, and
concurrent-family multiplicity binding are independently reconstructed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.repair_semantic_equivalence import (
    FIXED_HOLD_AUTHORITY_CORRECTION_FACTS_SCHEMA,
    RepairSemanticEquivalenceError,
    SEMANTIC_EQUIVALENCE_FACTS_SCHEMA,
    require_passed_fixed_hold_authority_correction_facts,
    require_passed_semantic_equivalence_facts,
)
from axiom_rift.operations.scientific_multiplicity_authority import (
    MULTIPLICITY_BATCH_BINDING_FIELDS,
    ScientificMultiplicityIntegrityError,
    build_multiplicity_batch_binding,
    concurrent_family_executable_ids,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class ReplayRepairScientificAuthorityError(RuntimeError):
    """A repaired replay Job is not exact scientific successor authority."""


_SELECTION_MULTIPLICITY_CRITERION = "E01-familywise-selection"
_MULTIPLICITY_REGISTRATION_FIELDS = {
    "alpha_ppm",
    "criterion_id",
    "family_id",
    "family_registration_hash",
    "family_size",
    "member_id",
    "method",
    "ordered_member_ids",
}


def request_executable_ids(request: Mapping[str, Any]) -> tuple[str, ...]:
    manifests = request.get("executable_manifests")
    if not isinstance(manifests, list) or any(
        not isinstance(manifest, Mapping) for manifest in manifests
    ):
        return ()
    return tuple(
        "executable:"
        + canonical_digest(domain="executable", payload=manifest)
        for manifest in manifests
    )


def request_member_binding(
    request: Mapping[str, Any],
    executable_id: str,
) -> Mapping[str, Any]:
    executable_ids = request_executable_ids(request)
    bindings = request.get("scientific_bindings")
    if (
        not executable_ids
        or executable_ids.count(executable_id) != 1
        or not isinstance(bindings, list)
        or len(bindings) != len(executable_ids)
        or any(not isinstance(binding, Mapping) for binding in bindings)
    ):
        raise ReplayRepairScientificAuthorityError(
            "repaired replay Job lacks one exact scientific family binding"
        )
    return bindings[executable_ids.index(executable_id)]


def request_validation_plan_hashes(
    request: Mapping[str, Any],
) -> tuple[str, ...]:
    bindings = request.get("scientific_bindings")
    if (
        not isinstance(bindings, list)
        or not bindings
        or any(
            not isinstance(binding, Mapping)
            or type(binding.get("validation_plan_hash")) is not str
            for binding in bindings
        )
    ):
        raise ReplayRepairScientificAuthorityError(
            "repaired replay request validation plans are malformed"
        )
    return tuple(sorted(binding["validation_plan_hash"] for binding in bindings))


def require_implementation_repair_semantics(
    index: LocalIndex | LocalIndexView,
    *,
    close: IndexRecord,
    executable_id: str,
) -> None:
    """Validate every production implementation edge, not only the stream head."""

    trial = index.get("trial", executable_id)
    validation = close.payload.get("semantic_equivalence_validation")
    binding = (
        None if not isinstance(validation, Mapping) else validation.get("binding")
    )
    facts = (
        None if not isinstance(validation, Mapping) else validation.get("facts")
    )
    trace = (
        None
        if not isinstance(validation, Mapping)
        else validation.get("registry_trace")
    )
    claims = (
        None if not isinstance(validation, Mapping) else validation.get("claims")
    )
    measurements = (
        None
        if not isinstance(validation, Mapping)
        else validation.get("measurement_artifact_hashes")
    )
    effective = close.payload.get("effective_implementation_identity")
    previous = close.payload.get("previous_effective_implementation_identity")
    if (
        trial is None
        or trial.status != "evaluated"
        or trial.fingerprint != executable_id.removeprefix("executable:")
        or trial.payload.get("engineering_fixture") is not False
        or trial.payload.get("scientific_eligible") is not True
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
        or facts.get("old_implementation_identity") != previous
        or facts.get("new_implementation_identity") != effective
        or binding.get("old_implementation_identity") != previous
        or binding.get("new_implementation_identity") != effective
        or binding.get("executable_id") != executable_id
        or binding.get("claims") != claims
        or measurements != binding.get("measurement_artifact_hashes")
        or binding.get("repair_id") != close.payload.get("repair_id")
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
        raise ReplayRepairScientificAuthorityError(
            "implementation Repair lacks complete production semantic authority"
        )
    try:
        if facts.get("schema") == SEMANTIC_EQUIVALENCE_FACTS_SCHEMA:
            require_passed_semantic_equivalence_facts(
                binding=binding,
                facts=facts,
            )
        elif facts.get("schema") == FIXED_HOLD_AUTHORITY_CORRECTION_FACTS_SCHEMA:
            require_passed_fixed_hold_authority_correction_facts(
                binding=binding,
                facts=facts,
            )
        else:
            raise RepairSemanticEquivalenceError(
                "implementation Repair facts protocol is unsupported"
            )
    except RepairSemanticEquivalenceError as exc:
        raise ReplayRepairScientificAuthorityError(
            "implementation Repair semantic facts are invalid"
        ) from exc


def require_implementation_semantic_successor(
    *,
    predecessor_close: IndexRecord,
    successor_close: IndexRecord,
) -> None:
    """Keep artifact and source closure continuous across multiple Repairs."""

    predecessor_validation = predecessor_close.payload.get(
        "semantic_equivalence_validation"
    )
    successor_validation = successor_close.payload.get(
        "semantic_equivalence_validation"
    )
    predecessor = (
        None
        if not isinstance(predecessor_validation, Mapping)
        else predecessor_validation.get("binding")
    )
    successor = (
        None
        if not isinstance(successor_validation, Mapping)
        else successor_validation.get("binding")
    )
    if (
        not isinstance(predecessor, Mapping)
        or not isinstance(successor, Mapping)
        or predecessor.get("new_implementation_identity")
        != successor.get("old_implementation_identity")
        or predecessor.get("new_implementation_artifact_hashes")
        != successor.get("old_implementation_artifact_hashes")
        or predecessor.get("new_source_closure_hash")
        != successor.get("old_source_closure_hash")
    ):
        raise ReplayRepairScientificAuthorityError(
            "implementation Repair semantic closures are discontinuous"
        )


def require_scientific_completion(
    *,
    completion: IndexRecord,
    declaration: IndexRecord,
    request: Mapping[str, Any],
    executable_id: str,
    batch_record: IndexRecord,
) -> None:
    binding = request_member_binding(request, executable_id)
    spec = declaration.payload.get("spec")
    scientific = completion.payload.get("scientific")
    try:
        family_ids = concurrent_family_executable_ids(batch_record)
    except ScientificMultiplicityIntegrityError as exc:
        raise ReplayRepairScientificAuthorityError(str(exc)) from exc
    batch_spec = batch_record.payload.get("spec")
    acceptance = (
        None
        if not isinstance(batch_spec, Mapping)
        else batch_spec.get("acceptance_profile")
    )
    family = (
        None
        if not isinstance(acceptance, Mapping)
        else acceptance.get("concurrent_family")
    )
    registrations = (
        None
        if not isinstance(scientific, Mapping)
        else scientific.get("multiplicity_registrations")
    )
    selection_matches = (
        ()
        if not isinstance(registrations, list)
        or any(not isinstance(item, Mapping) for item in registrations)
        else tuple(
            item
            for item in registrations
            if item.get("criterion_id") == _SELECTION_MULTIPLICITY_CRITERION
        )
    )
    selection = selection_matches[0] if len(selection_matches) == 1 else None
    projected = (
        None
        if not isinstance(scientific, Mapping)
        else scientific.get("multiplicity_batch_binding")
    )
    try:
        expected_projected = (
            None
            if not isinstance(family, Mapping)
            or family_ids is None
            or not isinstance(selection, Mapping)
            else build_multiplicity_batch_binding(
                batch_id=batch_record.record_id,
                concurrent_family=family,
                selection_registration=selection,
                executable_id=executable_id,
                ordered_member_ids=family_ids,
            )
        )
    except (KeyError, ScientificMultiplicityIntegrityError) as exc:
        raise ReplayRepairScientificAuthorityError(
            "repaired replay multiplicity registration is malformed"
        ) from exc
    completion_identity_payload = {
        "candidate_execution_context": completion.payload.get(
            "candidate_execution_context"
        ),
        "job_id": declaration.record_id,
        "outcome": completion.status,
        "outputs": completion.payload.get("outputs"),
        "failure_signature": (
            None
            if not isinstance(completion.payload.get("failure"), Mapping)
            else completion.payload["failure"].get("failure_signature")
        ),
        "external": completion.payload.get("external"),
        "runtime": completion.payload.get("runtime"),
        "repair_resume_record_id": completion.payload.get(
            "repair_resume_record_id"
        ),
        "scientific": scientific,
        "source": completion.payload.get("source"),
    }
    if "component_parity" in completion.payload:
        completion_identity_payload["component_parity"] = completion.payload.get(
            "component_parity"
        )
    expected_completion_id = canonical_digest(
        domain="job-completion",
        payload=completion_identity_payload,
    )
    expected_claims = binding.get("planned_claims")
    expected_modes = binding.get("evidence_modes")
    if (
        not isinstance(spec, Mapping)
        or spec.get("scientific_binding") != binding
        or not isinstance(scientific, Mapping)
        or completion.fingerprint != declaration.fingerprint
        or completion.record_id != expected_completion_id
        or scientific.get("scientific_eligible") is not True
        or type(scientific.get("candidate_eligible")) is not bool
        or (
            binding.get("evidence_depth") == "discovery"
            and scientific.get("candidate_eligible") is not False
        )
        or scientific.get("executable_id") != executable_id
        or scientific.get("validator_id") != binding.get("validator_id")
        or scientific.get("validation_plan_hash")
        != binding.get("validation_plan_hash")
        or scientific.get("evidence_depth") != binding.get("evidence_depth")
        or scientific.get("executed_evidence_modes") != expected_modes
        or scientific.get("claims") != sorted(expected_claims or ())
        or scientific.get("verdict")
        not in {"passed", "failed", "not_evaluable"}
        or family_ids is None
        or not isinstance(family, Mapping)
        or set(family_ids) != set(request_executable_ids(request))
        or not isinstance(selection, Mapping)
        or set(selection) != _MULTIPLICITY_REGISTRATION_FIELDS
        or selection.get("member_id") != executable_id
        or selection.get("family_size") != len(family_ids)
        or selection.get("ordered_member_ids") != list(family_ids)
        or not isinstance(projected, Mapping)
        or set(projected) != MULTIPLICITY_BATCH_BINDING_FIELDS
        or expected_projected is None
        or dict(projected) != expected_projected
    ):
        raise ReplayRepairScientificAuthorityError(
            "repaired replay Job scientific completion is malformed"
        )


__all__ = [
    "ReplayRepairScientificAuthorityError",
    "request_executable_ids",
    "request_member_binding",
    "request_validation_plan_hashes",
    "require_implementation_semantic_successor",
    "require_implementation_repair_semantics",
    "require_scientific_completion",
]
