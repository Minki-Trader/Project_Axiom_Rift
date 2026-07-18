"""Content-derived authority for one observed protected-semantic change.

This module deliberately proves only a local comparison fact: the proposed
successor changes one or more Writer-derived protected semantic surfaces.  It
does not prove that identity preservation is impossible, that the change is
necessary, or that every engineering route has been exhausted.

Caller-authored changed/protected labels are not accepted.  The comparison is
derived independently from the current and proposed Job, Executable, and
implementation-protocol artifacts through the existing semantic inventory
deriver.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.repair_semantic_equivalence import (
    RepairSemanticEquivalenceError,
    derive_semantic_surface_inventory,
)


class RepairSemanticChangeAuthorityError(ValueError):
    """Semantic-change authority is malformed, unbound, or not demonstrated."""


SEMANTIC_CHANGE_SUCCESSOR_ARTIFACT_SCHEMA = (
    "engineering_semantic_change_successor_artifact.v1"
)
SEMANTIC_CHANGE_PROPOSAL_SCHEMA = "engineering_semantic_change_proposal.v2"
SEMANTIC_CHANGE_CASE_SCHEMA = "engineering_semantic_change_case.v2"

_SUCCESSOR_SCOPES = frozenset({"executable", "study"})
_SUCCESSOR_ARTIFACT_FIELDS = {
    "executable_manifest",
    "implementation_protocol",
    "job_spec",
    "schema",
    "successor_scope",
}
_CURRENT_AUTHORITY_FIELDS = {
    "accepted_attempt_head_record_id",
    "current_basis_hash",
    "executable_id",
    "executable_manifest_sha256",
    "implementation_identity",
    "implementation_protocol_sha256",
    "job_hash",
    "job_id",
    "job_spec_sha256",
    "mission_id",
    "repair_id",
    "repair_validation_observation_head",
}
_PROPOSAL_FIELDS = {
    "current_authority",
    "proposed_successor_artifact_sha256",
    "schema",
    "successor_scope",
}
_CHANGED_SURFACE_FIELDS = {
    "category",
    "current_surface_id",
    "path",
    "proposed_surface_id",
}
_CASE_FIELDS = {
    "changed_surfaces",
    "current_authority",
    "current_surface_inventory_hash",
    "proposal_sha256",
    "proposed_successor_artifact_sha256",
    "proposed_surface_inventory_hash",
    "schema",
    "successor_scope",
}


def _document(
    value: bytes | Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    try:
        if type(value) is bytes:
            parsed = parse_canonical(value)
        elif isinstance(value, Mapping):
            parsed = parse_canonical(canonical_bytes(dict(value)))
        else:
            raise TypeError(f"{label} must be bytes or a mapping")
    except (TypeError, ValueError) as exc:
        raise RepairSemanticChangeAuthorityError(
            f"{label} is not canonical"
        ) from exc
    if type(parsed) is not dict:
        raise RepairSemanticChangeAuthorityError(f"{label} must be an object")
    return parsed


def _ascii(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RepairSemanticChangeAuthorityError(
            f"{label} must be non-empty ASCII"
        )
    return value


def _digest(label: str, value: object) -> str:
    text = _ascii(label, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise RepairSemanticChangeAuthorityError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return text


def _nullable_digest(label: str, value: object) -> str | None:
    return None if value is None else _digest(label, value)


def _typed_identity(label: str, value: object, prefix: str) -> str:
    text = _ascii(label, value)
    if not text.startswith(prefix):
        raise RepairSemanticChangeAuthorityError(
            f"{label} has an invalid identity prefix"
        )
    _digest(label, text.removeprefix(prefix))
    return text


def _canonical_sha256(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _canonical_mapping(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    return _document(value, label=label)


def _observation_head(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RepairSemanticChangeAuthorityError(
            "Repair validation observation head must be an object or null"
        )
    head = _canonical_mapping(
        value,
        label="Repair validation observation head",
    )
    if set(head) != {"fingerprint", "record_id", "sequence"}:
        raise RepairSemanticChangeAuthorityError(
            "Repair validation observation head schema is invalid"
        )
    sequence = head.get("sequence")
    if type(sequence) is not int or sequence < 1:
        raise RepairSemanticChangeAuthorityError(
            "Repair validation observation sequence must be positive"
        )
    return {
        "fingerprint": _digest(
            "Repair validation observation fingerprint",
            head.get("fingerprint"),
        ),
        "record_id": _digest(
            "Repair validation observation record",
            head.get("record_id"),
        ),
        "sequence": sequence,
    }


def _evidence_subject(
    job_spec: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, str]:
    value = job_spec.get("evidence_subject")
    if not isinstance(value, Mapping) or set(value) != {"id", "kind"}:
        raise RepairSemanticChangeAuthorityError(
            f"{label} evidence subject is invalid"
        )
    kind = _ascii(f"{label} evidence subject kind", value.get("kind"))
    identity = _ascii(f"{label} evidence subject identity", value.get("id"))
    if kind not in {"Executable", "Study"}:
        raise RepairSemanticChangeAuthorityError(
            f"{label} evidence subject kind is unsupported"
        )
    return {"id": identity, "kind": kind}


def _executable_identity(
    executable_manifest: Mapping[str, Any],
    *,
    label: str,
) -> str:
    if executable_manifest.get("schema") != "executable_spec.v1":
        raise RepairSemanticChangeAuthorityError(
            f"{label} Executable manifest schema is invalid"
        )
    return "executable:" + canonical_digest(
        domain="executable",
        payload=executable_manifest,
    )


def _current_authority(
    *,
    mission_id: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    current_executable_id: str,
    current_implementation_identity: str,
    current_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    current_implementation_protocol: str,
) -> dict[str, Any]:
    spec = _canonical_mapping(current_job_spec, label="current Job spec")
    manifest = _canonical_mapping(
        current_executable_manifest,
        label="current Executable manifest",
    )
    protocol = _ascii(
        "current implementation protocol",
        current_implementation_protocol,
    )
    mission = _ascii("current Mission identity", mission_id)
    repair = _typed_identity("current Repair identity", repair_id, "repair:")
    job = _typed_identity("current Job identity", job_id, "job:")
    job_fingerprint = _digest("current Job hash", job_hash)
    if job.removeprefix("job:") != job_fingerprint:
        raise RepairSemanticChangeAuthorityError(
            "current Job identity differs from its Job hash"
        )
    executable = _typed_identity(
        "current Executable identity",
        current_executable_id,
        "executable:",
    )
    if executable != _executable_identity(manifest, label="current"):
        raise RepairSemanticChangeAuthorityError(
            "current Executable identity differs from its exact manifest"
        )
    implementation = _digest(
        "current implementation identity",
        current_implementation_identity,
    )
    if spec.get("implementation_identity") != implementation:
        raise RepairSemanticChangeAuthorityError(
            "current implementation identity differs from the Job spec"
        )
    subject = _evidence_subject(spec, label="current Job")
    if subject["kind"] == "Executable" and subject["id"] != executable:
        raise RepairSemanticChangeAuthorityError(
            "current Job subject differs from the current Executable"
        )
    return {
        "accepted_attempt_head_record_id": _nullable_digest(
            "accepted Repair attempt head",
            accepted_attempt_head_record_id,
        ),
        "current_basis_hash": _digest(
            "current Repair basis",
            current_basis_hash,
        ),
        "executable_id": executable,
        "executable_manifest_sha256": _canonical_sha256(manifest),
        "implementation_identity": implementation,
        "implementation_protocol_sha256": _canonical_sha256(protocol),
        "job_hash": job_fingerprint,
        "job_id": job,
        "job_spec_sha256": _canonical_sha256(spec),
        "mission_id": mission,
        "repair_id": repair,
        "repair_validation_observation_head": _observation_head(
            repair_validation_observation_head
        ),
    }


def build_semantic_change_successor_artifact(
    *,
    successor_scope: str,
    job_spec: Mapping[str, Any],
    executable_manifest: Mapping[str, Any],
    implementation_protocol: str,
) -> dict[str, Any]:
    """Build the one canonical artifact containing the proposed triple."""

    value = {
        "executable_manifest": _canonical_mapping(
            executable_manifest,
            label="proposed Executable manifest",
        ),
        "implementation_protocol": _ascii(
            "proposed implementation protocol",
            implementation_protocol,
        ),
        "job_spec": _canonical_mapping(job_spec, label="proposed Job spec"),
        "schema": SEMANTIC_CHANGE_SUCCESSOR_ARTIFACT_SCHEMA,
        "successor_scope": successor_scope,
    }
    return normalize_semantic_change_successor_artifact(value)


def normalize_semantic_change_successor_artifact(
    value: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Require the exact successor artifact schema and internal identities."""

    document = _document(value, label="semantic-change successor artifact")
    if (
        set(document) != _SUCCESSOR_ARTIFACT_FIELDS
        or document.get("schema") != SEMANTIC_CHANGE_SUCCESSOR_ARTIFACT_SCHEMA
        or document.get("successor_scope") not in _SUCCESSOR_SCOPES
    ):
        raise RepairSemanticChangeAuthorityError(
            "semantic-change successor artifact schema is invalid"
        )
    spec_value = document.get("job_spec")
    manifest_value = document.get("executable_manifest")
    if not isinstance(spec_value, Mapping) or not isinstance(
        manifest_value, Mapping
    ):
        raise RepairSemanticChangeAuthorityError(
            "semantic-change successor triple is invalid"
        )
    spec = _canonical_mapping(spec_value, label="proposed Job spec")
    manifest = _canonical_mapping(
        manifest_value,
        label="proposed Executable manifest",
    )
    protocol = _ascii(
        "proposed implementation protocol",
        document.get("implementation_protocol"),
    )
    implementation = _digest(
        "proposed implementation identity",
        spec.get("implementation_identity"),
    )
    if spec.get("implementation_identity") != implementation:
        raise RepairSemanticChangeAuthorityError(
            "proposed Job implementation identity is invalid"
        )
    scope = str(document["successor_scope"])
    subject = _evidence_subject(spec, label="proposed Job")
    expected_kind = "Executable" if scope == "executable" else "Study"
    if subject["kind"] != expected_kind:
        raise RepairSemanticChangeAuthorityError(
            "proposed Job subject differs from successor_scope"
        )
    executable = _executable_identity(manifest, label="proposed")
    if expected_kind == "Executable" and subject["id"] != executable:
        raise RepairSemanticChangeAuthorityError(
            "proposed Job subject differs from its exact Executable manifest"
        )
    if expected_kind == "Study" and not subject["id"].startswith("STU-"):
        raise RepairSemanticChangeAuthorityError(
            "proposed Study identity prefix is invalid"
        )
    return {
        "executable_manifest": manifest,
        "implementation_protocol": protocol,
        "job_spec": spec,
        "schema": SEMANTIC_CHANGE_SUCCESSOR_ARTIFACT_SCHEMA,
        "successor_scope": scope,
    }


def build_semantic_change_proposal(
    *,
    mission_id: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    current_executable_id: str,
    current_implementation_identity: str,
    current_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    current_implementation_protocol: str,
    proposed_successor_artifact: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Bind exact current authority to one content-addressed successor."""

    successor = normalize_semantic_change_successor_artifact(
        proposed_successor_artifact
    )
    return {
        "current_authority": _current_authority(
            mission_id=mission_id,
            repair_id=repair_id,
            job_id=job_id,
            job_hash=job_hash,
            current_basis_hash=current_basis_hash,
            accepted_attempt_head_record_id=accepted_attempt_head_record_id,
            repair_validation_observation_head=(
                repair_validation_observation_head
            ),
            current_executable_id=current_executable_id,
            current_implementation_identity=current_implementation_identity,
            current_job_spec=current_job_spec,
            current_executable_manifest=current_executable_manifest,
            current_implementation_protocol=current_implementation_protocol,
        ),
        "proposed_successor_artifact_sha256": _canonical_sha256(successor),
        "schema": SEMANTIC_CHANGE_PROPOSAL_SCHEMA,
        "successor_scope": successor["successor_scope"],
    }


def normalize_semantic_change_proposal(
    value: bytes | Mapping[str, Any],
    *,
    mission_id: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    current_executable_id: str,
    current_implementation_identity: str,
    current_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    current_implementation_protocol: str,
    proposed_successor_artifact: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Authenticate a proposal against current authority and successor bytes."""

    document = _document(value, label="semantic-change proposal")
    if (
        set(document) != _PROPOSAL_FIELDS
        or document.get("schema") != SEMANTIC_CHANGE_PROPOSAL_SCHEMA
        or not isinstance(document.get("current_authority"), Mapping)
        or set(document["current_authority"]) != _CURRENT_AUTHORITY_FIELDS
    ):
        raise RepairSemanticChangeAuthorityError(
            "semantic-change proposal schema is invalid"
        )
    expected = build_semantic_change_proposal(
        mission_id=mission_id,
        repair_id=repair_id,
        job_id=job_id,
        job_hash=job_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempt_head_record_id=accepted_attempt_head_record_id,
        repair_validation_observation_head=repair_validation_observation_head,
        current_executable_id=current_executable_id,
        current_implementation_identity=current_implementation_identity,
        current_job_spec=current_job_spec,
        current_executable_manifest=current_executable_manifest,
        current_implementation_protocol=current_implementation_protocol,
        proposed_successor_artifact=proposed_successor_artifact,
    )
    if document != expected:
        raise RepairSemanticChangeAuthorityError(
            "semantic-change proposal differs from exact current authority or "
            "successor artifact"
        )
    return expected


def _surface_inventory(
    *,
    label: str,
    job_spec: Mapping[str, Any],
    executable_manifest: Mapping[str, Any],
    implementation_protocol: str,
) -> tuple[dict[str, str], ...]:
    try:
        inventory = derive_semantic_surface_inventory(
            job_spec=job_spec,
            executable_manifest=executable_manifest,
            implementation_protocol=implementation_protocol,
        )
    except (RepairSemanticEquivalenceError, TypeError, ValueError) as exc:
        raise RepairSemanticChangeAuthorityError(
            f"{label} semantic surface inventory is invalid"
        ) from exc
    if not inventory:
        raise RepairSemanticChangeAuthorityError(
            f"{label} semantic surface inventory is empty"
        )
    return inventory


def _surface_inventory_hash(inventory: tuple[dict[str, str], ...]) -> str:
    return canonical_digest(
        domain="implementation-repair-semantic-surface-inventory",
        payload={"surface_inventory": [dict(item) for item in inventory]},
    )


def _changed_surfaces(
    *,
    current: tuple[dict[str, str], ...],
    proposed: tuple[dict[str, str], ...],
) -> list[dict[str, str]]:
    current_by_path = {item["path"]: item for item in current}
    proposed_by_path = {item["path"]: item for item in proposed}
    if len(current_by_path) != len(current) or len(proposed_by_path) != len(
        proposed
    ):
        raise RepairSemanticChangeAuthorityError(
            "semantic surface path inventory is ambiguous"
        )
    if set(current_by_path) != set(proposed_by_path):
        raise RepairSemanticChangeAuthorityError(
            "proposed successor omits or adds a protected semantic surface path"
        )
    changed: list[dict[str, str]] = []
    for path in sorted(current_by_path):
        current_item = current_by_path[path]
        proposed_item = proposed_by_path[path]
        if current_item["category"] != proposed_item["category"]:
            raise RepairSemanticChangeAuthorityError(
                "proposed successor changes semantic surface path category"
            )
        value_changed = current_item["value_hash"] != proposed_item["value_hash"]
        identity_changed = (
            current_item["surface_id"] != proposed_item["surface_id"]
        )
        if value_changed != identity_changed:
            raise RepairSemanticChangeAuthorityError(
                "semantic surface identity differs from its value comparison"
            )
        if value_changed:
            changed.append(
                {
                    "category": current_item["category"],
                    "current_surface_id": current_item["surface_id"],
                    "path": path,
                    "proposed_surface_id": proposed_item["surface_id"],
                }
            )
    if not changed:
        raise RepairSemanticChangeAuthorityError(
            "proposed successor changes no protected semantic surface"
        )
    return changed


def derive_semantic_change_case(
    *,
    proposal: bytes | Mapping[str, Any],
    mission_id: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    current_executable_id: str,
    current_implementation_identity: str,
    current_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    current_implementation_protocol: str,
    proposed_successor_artifact: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Derive a v2 case from two independently inventoried semantic triples."""

    normalized_proposal = normalize_semantic_change_proposal(
        proposal,
        mission_id=mission_id,
        repair_id=repair_id,
        job_id=job_id,
        job_hash=job_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempt_head_record_id=accepted_attempt_head_record_id,
        repair_validation_observation_head=repair_validation_observation_head,
        current_executable_id=current_executable_id,
        current_implementation_identity=current_implementation_identity,
        current_job_spec=current_job_spec,
        current_executable_manifest=current_executable_manifest,
        current_implementation_protocol=current_implementation_protocol,
        proposed_successor_artifact=proposed_successor_artifact,
    )
    successor = normalize_semantic_change_successor_artifact(
        proposed_successor_artifact
    )
    current_inventory = _surface_inventory(
        label="current",
        job_spec=current_job_spec,
        executable_manifest=current_executable_manifest,
        implementation_protocol=current_implementation_protocol,
    )
    proposed_inventory = _surface_inventory(
        label="proposed",
        job_spec=successor["job_spec"],
        executable_manifest=successor["executable_manifest"],
        implementation_protocol=successor["implementation_protocol"],
    )
    return {
        "changed_surfaces": _changed_surfaces(
            current=current_inventory,
            proposed=proposed_inventory,
        ),
        "current_authority": dict(normalized_proposal["current_authority"]),
        "current_surface_inventory_hash": _surface_inventory_hash(
            current_inventory
        ),
        "proposal_sha256": _canonical_sha256(normalized_proposal),
        "proposed_successor_artifact_sha256": normalized_proposal[
            "proposed_successor_artifact_sha256"
        ],
        "proposed_surface_inventory_hash": _surface_inventory_hash(
            proposed_inventory
        ),
        "schema": SEMANTIC_CHANGE_CASE_SCHEMA,
        "successor_scope": normalized_proposal["successor_scope"],
    }


def normalize_semantic_change_case(
    value: bytes | Mapping[str, Any],
    *,
    proposal: bytes | Mapping[str, Any],
    mission_id: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    current_executable_id: str,
    current_implementation_identity: str,
    current_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    current_implementation_protocol: str,
    proposed_successor_artifact: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute and authenticate one stored semantic-change case."""

    document = _document(value, label="semantic-change case")
    changed = document.get("changed_surfaces")
    if (
        set(document) != _CASE_FIELDS
        or document.get("schema") != SEMANTIC_CHANGE_CASE_SCHEMA
        or not isinstance(document.get("current_authority"), Mapping)
        or set(document["current_authority"]) != _CURRENT_AUTHORITY_FIELDS
        or not isinstance(changed, list)
        or not changed
        or any(
            not isinstance(item, Mapping)
            or set(item) != _CHANGED_SURFACE_FIELDS
            for item in changed
        )
    ):
        raise RepairSemanticChangeAuthorityError(
            "semantic-change case schema is invalid"
        )
    expected = derive_semantic_change_case(
        proposal=proposal,
        mission_id=mission_id,
        repair_id=repair_id,
        job_id=job_id,
        job_hash=job_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempt_head_record_id=accepted_attempt_head_record_id,
        repair_validation_observation_head=repair_validation_observation_head,
        current_executable_id=current_executable_id,
        current_implementation_identity=current_implementation_identity,
        current_job_spec=current_job_spec,
        current_executable_manifest=current_executable_manifest,
        current_implementation_protocol=current_implementation_protocol,
        proposed_successor_artifact=proposed_successor_artifact,
    )
    if document != expected:
        raise RepairSemanticChangeAuthorityError(
            "semantic-change case differs from independently derived surfaces"
        )
    return expected


def semantic_change_facts(
    value: bytes | Mapping[str, Any],
    *,
    proposal: bytes | Mapping[str, Any],
    mission_id: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    current_executable_id: str,
    current_implementation_identity: str,
    current_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    current_implementation_protocol: str,
    proposed_successor_artifact: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Return only the local, content-derived semantic-change facts."""

    case = normalize_semantic_change_case(
        value,
        proposal=proposal,
        mission_id=mission_id,
        repair_id=repair_id,
        job_id=job_id,
        job_hash=job_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempt_head_record_id=accepted_attempt_head_record_id,
        repair_validation_observation_head=repair_validation_observation_head,
        current_executable_id=current_executable_id,
        current_implementation_identity=current_implementation_identity,
        current_job_spec=current_job_spec,
        current_executable_manifest=current_executable_manifest,
        current_implementation_protocol=current_implementation_protocol,
        proposed_successor_artifact=proposed_successor_artifact,
    )
    pairs = [
        {
            "current_surface_id": item["current_surface_id"],
            "path": item["path"],
            "proposed_surface_id": item["proposed_surface_id"],
        }
        for item in case["changed_surfaces"]
    ]
    return {
        "changed_surface_id_pairs": pairs,
        "changed_surface_paths": [item["path"] for item in pairs],
        "this_correction_changes_protected_semantics": True,
    }


__all__ = [
    "SEMANTIC_CHANGE_CASE_SCHEMA",
    "SEMANTIC_CHANGE_PROPOSAL_SCHEMA",
    "SEMANTIC_CHANGE_SUCCESSOR_ARTIFACT_SCHEMA",
    "RepairSemanticChangeAuthorityError",
    "build_semantic_change_proposal",
    "build_semantic_change_successor_artifact",
    "derive_semantic_change_case",
    "normalize_semantic_change_case",
    "normalize_semantic_change_proposal",
    "normalize_semantic_change_successor_artifact",
    "semantic_change_facts",
]
