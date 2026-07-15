"""Exact concurrent-family and scientific multiplicity authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.index import IndexRecord, LocalIndex


class ScientificMultiplicityAuthorityError(RuntimeError):
    """A requested family or multiplicity binding is not authorized."""


class ScientificMultiplicityIntegrityError(RuntimeError):
    """Durable family authority is malformed or internally inconsistent."""


MULTIPLICITY_BATCH_BINDING_FIELDS = frozenset(
    {
        "batch_id",
        "binding_hash",
        "concurrent_family_identity",
        "criterion_id",
        "executable_id",
        "family_id",
        "family_registration_hash",
        "family_size",
        "ordered_member_ids",
        "schema",
    }
)


def _require_ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificMultiplicityAuthorityError(
            f"{name} must be non-empty ASCII"
        )
    return value


def _require_digest(name: str, value: object) -> str:
    result = _require_ascii(name, value)
    if len(result) != 64 or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise ScientificMultiplicityAuthorityError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return result


def concurrent_family_executable_ids(
    batch_record: IndexRecord,
) -> tuple[str, ...] | None:
    """Rebuild and verify the exact typed family frozen into one Batch."""

    from axiom_rift.research.portfolio import (
        BatchSpecError,
        ConcurrentFamilyEvaluationMode,
        ConcurrentFamilyManifest,
    )

    spec = batch_record.payload.get("spec")
    acceptance = (
        None if not isinstance(spec, dict) else spec.get("acceptance_profile")
    )
    if not isinstance(acceptance, dict):
        raise ScientificMultiplicityIntegrityError(
            "Batch acceptance profile is unavailable"
        )
    payload = acceptance.get("concurrent_family")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ScientificMultiplicityIntegrityError(
            "concurrent family manifest is malformed"
        )
    try:
        manifest = ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode(
                payload["evaluation_mode"]
            ),
            executable_ids=tuple(payload["executable_ids"]),
        )
    except (BatchSpecError, KeyError, TypeError, ValueError) as exc:
        raise ScientificMultiplicityIntegrityError(
            "concurrent family manifest is malformed"
        ) from exc
    if (
        payload != manifest.to_identity_payload()
        or spec.get("max_trials") != manifest.family_size
    ):
        raise ScientificMultiplicityIntegrityError(
            "concurrent family manifest differs from the frozen Batch bound"
        )
    return manifest.executable_ids


def require_concurrent_family_registration(
    index: LocalIndex,
    *,
    batch_record: IndexRecord,
    evidence_subject: Mapping[str, Any],
) -> None:
    """Block family engine entry until every exact member is durably counted."""

    executable_ids = concurrent_family_executable_ids(batch_record)
    if executable_ids is None:
        return
    subject_id = evidence_subject.get("id")
    if (
        evidence_subject.get("kind") != "Executable"
        or subject_id not in executable_ids
    ):
        raise ScientificMultiplicityAuthorityError(
            "concurrent family Job subject is outside the exact frozen family"
        )
    missing: list[str] = []
    for executable_id in executable_ids:
        trial = index.get("trial", executable_id)
        if trial is None:
            trial = index.get("engineering-evaluation-fixture", executable_id)
        if (
            trial is None
            or trial.fingerprint != executable_id.removeprefix("executable:")
            or trial.status not in {"evaluated", "engineering_only"}
        ):
            missing.append(executable_id)
    if missing:
        raise ScientificMultiplicityAuthorityError(
            "concurrent family Job cannot start before every exact family trial "
            f"is registered ({len(missing)} missing)"
        )


def build_multiplicity_batch_binding(
    *,
    batch_id: str,
    concurrent_family: Mapping[str, Any],
    selection_registration: Mapping[str, Any],
    executable_id: str,
    ordered_member_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Derive the canonical durable E01 registration-to-Batch binding."""

    binding_payload = {
        "batch_id": batch_id,
        "concurrent_family_identity": "concurrent-family:"
        + canonical_digest(
            domain="concurrent-family-manifest",
            payload=dict(concurrent_family),
        ),
        "criterion_id": selection_registration["criterion_id"],
        "executable_id": executable_id,
        "family_id": selection_registration["family_id"],
        "family_registration_hash": selection_registration[
            "family_registration_hash"
        ],
        "family_size": len(ordered_member_ids),
        "ordered_member_ids": list(ordered_member_ids),
        "schema": "scientific_multiplicity_batch_binding.v1",
    }
    return {
        **binding_payload,
        "binding_hash": canonical_digest(
            domain="scientific-multiplicity-batch-binding",
            payload=binding_payload,
        ),
    }


def _load_multiplicity_plan(
    *,
    binding: Mapping[str, Any],
    registrations: object,
    executable_id: str,
    mission_id: str,
    artifact_reader: Callable[[str], bytes],
) -> Mapping[str, Any] | None:
    plan_hash = binding.get("validation_plan_hash")
    if type(plan_hash) is not str:
        raise ScientificMultiplicityAuthorityError(
            "scientific validation plan hash is absent"
        )
    try:
        plan = parse_canonical(artifact_reader(plan_hash))
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise ScientificMultiplicityAuthorityError(
            "scientific validation plan is unavailable"
        ) from exc
    if (
        not isinstance(plan, Mapping)
        or plan.get("schema") != "scientific_validation_plan.v2"
    ):
        if registrations is not None:
            raise ScientificMultiplicityAuthorityError(
                "legacy scientific validation returned v2 multiplicity registrations"
            )
        return None
    if (
        plan.get("executable_id") != executable_id
        or plan.get("mission_id") != mission_id
    ):
        raise ScientificMultiplicityAuthorityError(
            "scientific validation plan belongs to another Mission or Executable"
        )
    return plan


def _validated_registration_metadata(
    item: Mapping[str, Any],
) -> tuple[str, str, tuple[object, ...]]:
    criterion_id = _require_ascii(
        "scientific multiplicity criterion", item["criterion_id"]
    )
    family_id = _require_ascii(
        "scientific multiplicity family", item["family_id"]
    )
    method = _require_ascii(
        "scientific multiplicity method", item["method"]
    )
    member_id = _require_ascii(
        "scientific multiplicity member", item["member_id"]
    )
    alpha_ppm = item["alpha_ppm"]
    family_size = item["family_size"]
    members = item["ordered_member_ids"]
    if (
        type(alpha_ppm) is not int
        or not 1 <= alpha_ppm <= 1_000_000
        or type(family_size) is not int
        or family_size < 1
        or not isinstance(members, list)
        or len(members) != family_size
        or len(set(members)) != family_size
        or any(
            type(member) is not str
            or not member
            or not member.isascii()
            for member in members
        )
        or member_id not in members
    ):
        raise ScientificMultiplicityAuthorityError(
            "scientific multiplicity registration membership is malformed"
        )
    registration_hash = _require_digest(
        "scientific multiplicity family registration",
        item["family_registration_hash"],
    )
    expected_hash = canonical_digest(
        domain="scientific-v2-multiplicity-family",
        payload={
            "alpha_ppm": alpha_ppm,
            "family_id": family_id,
            "family_size": family_size,
            "method": method,
            "ordered_member_ids": list(members),
            "schema": "scientific_multiplicity_family_registration.v1",
        },
    )
    if registration_hash != expected_hash:
        raise ScientificMultiplicityAuthorityError(
            "scientific multiplicity family registration hash is invalid"
        )
    return criterion_id, family_id, (
        family_size,
        alpha_ppm,
        method,
        tuple(members),
        registration_hash,
    )


def _validate_registration_inventory(
    registrations: object,
    *,
    expected: object,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    fields = {
        "alpha_ppm",
        "criterion_id",
        "family_id",
        "family_registration_hash",
        "family_size",
        "member_id",
        "method",
        "ordered_member_ids",
    }
    if (
        not isinstance(registrations, list)
        or not isinstance(expected, list)
        or registrations != expected
        or any(
            not isinstance(item, Mapping) or set(item) != fields
            for item in registrations
        )
    ):
        raise ScientificMultiplicityAuthorityError(
            "scientific multiplicity registrations differ from the durable plan"
        )
    rows = [item for item in registrations if isinstance(item, Mapping)]
    criterion_ids: list[str] = []
    family_metadata: dict[str, tuple[object, ...]] = {}
    for item in rows:
        criterion_id, family_id, metadata = (
            _validated_registration_metadata(item)
        )
        previous = family_metadata.setdefault(family_id, metadata)
        if previous != metadata:
            raise ScientificMultiplicityAuthorityError(
                "scientific multiplicity family metadata is inconsistent"
            )
        criterion_ids.append(criterion_id)
    if criterion_ids != sorted(set(criterion_ids)):
        raise ScientificMultiplicityAuthorityError(
            "scientific multiplicity registrations are not canonical"
        )
    return rows, criterion_ids


def _require_adjudication_inventory(
    registrations: list[Mapping[str, Any]],
    *,
    criterion_ids: list[str],
    adjudication: object,
) -> None:
    rows = (
        None
        if not isinstance(adjudication, Mapping)
        else adjudication.get("multiplicity")
    )
    if not isinstance(rows, list) or len(rows) != len(registrations):
        raise ScientificMultiplicityAuthorityError(
            "scientific adjudication lost its multiplicity inventory"
        )
    by_criterion = {
        row.get("criterion_id"): row
        for row in rows
        if isinstance(row, Mapping)
        and type(row.get("criterion_id")) is str
    }
    if set(by_criterion) != set(criterion_ids) or len(by_criterion) != len(rows):
        raise ScientificMultiplicityAuthorityError(
            "scientific adjudication multiplicity inventory is ambiguous"
        )
    for item in registrations:
        row = by_criterion[item["criterion_id"]]
        if any(
            row.get(name) != item[name]
            for name in (
                "alpha_ppm",
                "criterion_id",
                "family_id",
                "family_size",
                "method",
            )
        ):
            raise ScientificMultiplicityAuthorityError(
                "scientific adjudication differs from its family registration"
            )


def _bind_selection_registration_to_batch(
    registrations: list[Mapping[str, Any]],
    *,
    batch_record: IndexRecord | None,
    expected_batch_id: str | None,
    executable_id: str,
) -> dict[str, Any] | None:
    selection_registrations = [
        item
        for item in registrations
        if item["criterion_id"] == "E01-familywise-selection"
    ]
    batch_family = (
        None
        if batch_record is None
        else concurrent_family_executable_ids(batch_record)
    )
    if batch_record is not None and batch_record.record_id != expected_batch_id:
        raise ScientificMultiplicityAuthorityError(
            "scientific multiplicity registration belongs to another Batch"
        )
    if batch_family is None:
        if selection_registrations:
            raise ScientificMultiplicityAuthorityError(
                "E01 multiplicity registration lacks an exact concurrent Batch"
            )
        return None
    if (
        batch_record is None
        or batch_record.kind != "batch-open"
        or batch_record.status != "open"
        or len(selection_registrations) != 1
    ):
        raise ScientificMultiplicityAuthorityError(
            "concurrent Batch requires one exact E01 multiplicity registration"
        )
    selection = selection_registrations[0]
    batch_spec = batch_record.payload.get("spec")
    acceptance = (
        None
        if not isinstance(batch_spec, Mapping)
        else batch_spec.get("acceptance_profile")
    )
    concurrent = (
        None
        if not isinstance(acceptance, Mapping)
        else acceptance.get("concurrent_family")
    )
    if (
        not isinstance(concurrent, Mapping)
        or selection["ordered_member_ids"] != list(batch_family)
        or set(selection["ordered_member_ids"]) != set(batch_family)
        or selection["family_size"] != len(batch_family)
        or selection["member_id"] != executable_id
        or executable_id not in batch_family
    ):
        raise ScientificMultiplicityAuthorityError(
            "E01 multiplicity registration differs from its exact Batch family"
        )
    return build_multiplicity_batch_binding(
        batch_id=batch_record.record_id,
        concurrent_family=concurrent,
        selection_registration=selection,
        executable_id=executable_id,
        ordered_member_ids=batch_family,
    )


def validate_scientific_multiplicity_registrations(
    *,
    binding: Mapping[str, Any],
    registrations: object,
    adjudication: object,
    batch_record: IndexRecord | None,
    expected_batch_id: str | None,
    executable_id: str,
    mission_id: str,
    artifact_reader: Callable[[str], bytes],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Bind a v2 completion to its exact durable prospective families."""

    plan = _load_multiplicity_plan(
        binding=binding,
        registrations=registrations,
        executable_id=executable_id,
        mission_id=mission_id,
        artifact_reader=artifact_reader,
    )
    if plan is None:
        return None, None
    profile = plan.get("adjudication_profile")
    expected = (
        None if not isinstance(profile, Mapping) else profile.get("multiplicity")
    )
    registration_rows, criterion_ids = _validate_registration_inventory(
        registrations,
        expected=expected,
    )
    _require_adjudication_inventory(
        registration_rows,
        criterion_ids=criterion_ids,
        adjudication=adjudication,
    )
    multiplicity_batch_binding = _bind_selection_registration_to_batch(
        registration_rows,
        batch_record=batch_record,
        expected_batch_id=expected_batch_id,
        executable_id=executable_id,
    )

    normalized = parse_canonical(canonical_bytes(registration_rows))
    assert isinstance(normalized, list)
    return (
        [dict(item) for item in normalized],
        multiplicity_batch_binding,
    )


__all__ = [
    "MULTIPLICITY_BATCH_BINDING_FIELDS",
    "ScientificMultiplicityAuthorityError",
    "ScientificMultiplicityIntegrityError",
    "build_multiplicity_batch_binding",
    "concurrent_family_executable_ids",
    "require_concurrent_family_registration",
    "validate_scientific_multiplicity_registrations",
]
