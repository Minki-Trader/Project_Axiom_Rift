"""Outcome-free Repair candidate construction for Writer fixtures.

The helper writes only a proposed candidate plus raw fixture measurements.
The registered fixture validator, not this helper or the candidate, derives the
accepted or zero-credit evaluation mode.
"""

from __future__ import annotations

from collections.abc import Sequence

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.repair_candidate import build_repair_candidate
from axiom_rift.operations.repair_disposition_materializer import (
    materialize_engineering_repair_disposition,
)
from axiom_rift.operations.repair_observation_authority import (
    require_repair_validation_observation_stream,
)
from axiom_rift.operations.repair_validation import (
    build_repair_candidate_validation_context,
    build_repair_candidate_validation_receipt,
    build_repair_validation_plan,
    repair_validation_binding,
)
from axiom_rift.operations.validation import (
    ENGINEERING_REPAIR_FIXTURE_PROTOCOL,
    ENGINEERING_REPAIR_FIXTURE_VALIDATOR_ID,
    EngineeringRepairFixtureValidator,
)
from axiom_rift.operations.writer import StateWriter
from tests.operations.fixture_validators import (
    EngineeringRepairBoundaryFixtureValidator,
)


def repair_candidate_fixture(
    writer: StateWriter,
    *,
    failure_observed_after_change: bool,
    changed_dimension: str,
    new_basis_hash: str,
    new_evidence_hashes: Sequence[str],
    support_evidence_hashes: Sequence[str] = (),
    implementation_proof_hash: str | None = None,
    material_change_observed: bool = True,
    measurement_complete: bool = True,
    repair_axis_id: str | None = None,
    validator_id_override: str | None = None,
) -> str:
    """Build one candidate whose terminal meaning is absent from its bytes."""

    control = writer.read_control()
    if control is None:
        raise AssertionError("fixture control is absent")
    repair = control["scientific"]["active_repair"]
    job = control["scientific"]["active_job"]
    mission_id = control["scientific"]["active_mission"]
    if not isinstance(repair, dict) or not isinstance(job, dict):
        raise AssertionError("fixture Repair or Job is absent")
    if not isinstance(mission_id, str):
        raise AssertionError("fixture Mission is absent")

    with writer.open_stable_index() as (_stable_control, index):
        opened = index.get("repair-open", str(repair["id"]))
        if opened is None:
            raise AssertionError("fixture Repair open record is absent")
        attempts = []
        attempt_head = index.event_head(f"repair-attempt:{repair['id']}")
        if attempt_head is not None:
            for sequence in range(1, attempt_head.sequence + 1):
                attempt = index.event_record(
                    f"repair-attempt:{repair['id']}", sequence
                )
                if attempt is None:
                    raise AssertionError("fixture Repair attempt stream has a gap")
                attempts.append(attempt)
        observations, observation_head = (
            require_repair_validation_observation_stream(
                index,
                repair_id=str(repair["id"]),
                job_id=str(job["id"]),
                job_hash=str(job["hash"]),
                cause_hash=str(repair["cause_hash"]),
                reproduction_evidence_hashes=tuple(
                    opened.payload["minimum_reproduction_evidence"]
                ),
                resume_action=str(repair["resume_action"]),
                mission_id=mission_id,
                expected_scope=(
                    "fixture_only" if writer.engineering_fixture else "production"
                ),
                accepted_attempts=attempts,
                evidence=writer.evidence,
            )
        )

    bound_observations = tuple(
        {
            "new_information_evidence_hashes": list(
                item["new_information_evidence_hashes"]
            ),
            "observation_record_id": item["observation_record_id"],
        }
        for item in observations
    )
    changed_evidence = {
        new_basis_hash,
        *new_evidence_hashes,
        *(
            identity
            for item in bound_observations
            for identity in item["new_information_evidence_hashes"]
        ),
    }
    if implementation_proof_hash is not None:
        changed_evidence.add(implementation_proof_hash)
    changed_evidence_hashes = tuple(sorted(changed_evidence))
    axis_id = repair_axis_id or (
        f"{changed_dimension}-fixture-axis-{new_basis_hash[:16]}"
    )
    context = build_repair_candidate_validation_context(
        bound_validation_observations=bound_observations,
        cause_hash=str(repair["cause_hash"]),
        changed_dimension=changed_dimension,
        explanation="evaluate the changed fixture basis",
        implementation_proof_hash=implementation_proof_hash,
        job_hash=str(job["hash"]),
        job_id=str(job["id"]),
        new_basis_hash=new_basis_hash,
        new_evidence_hashes=changed_evidence_hashes,
        previous_basis_hash=str(repair["latest_basis_hash"]),
        prior_attempt_record_id=repair["latest_attempt_record_id"],
        prior_validation_observation_head=observation_head,
        repair_axis_id=axis_id,
        repair_id=str(repair["id"]),
        reproduction_evidence_hashes=tuple(
            opened.payload["minimum_reproduction_evidence"]
        ),
        resume_action=str(repair["resume_action"]),
    )
    support_hashes = tuple(sorted(set(support_evidence_hashes)))
    result = writer.evidence.finalize(
        canonical_bytes(
            {
                "failure_observed_after_change": failure_observed_after_change,
                "material_change_observed": material_change_observed,
                "measurement_complete": measurement_complete,
                "observed_context": context,
                "schema": (
                    "engineering_repair_candidate_fixture_measurement.v1"
                ),
                "support_artifact_hashes": list(support_hashes),
            }
        )
    )
    protocol = (
        ENGINEERING_REPAIR_FIXTURE_PROTOCOL
        if writer.engineering_fixture
        else EngineeringRepairBoundaryFixtureValidator.protocol
    )
    validator_id = (
        ENGINEERING_REPAIR_FIXTURE_VALIDATOR_ID
        if writer.engineering_fixture
        else EngineeringRepairBoundaryFixtureValidator.validator_id
    )
    if validator_id_override is not None:
        validator_id = validator_id_override
    roles = tuple(
        sorted(
            (
                ("validation_result", result.sha256),
                *(
                    (f"support:{ordinal:04d}", identity)
                    for ordinal, identity in enumerate(support_hashes)
                ),
            )
        )
    )
    binding = repair_validation_binding(
        verification_kind="candidate",
        mission_id=mission_id,
        protocol=protocol,
        context=context,
        artifact_roles=roles,
    )
    plan = writer.evidence.finalize(
        canonical_bytes(
            build_repair_validation_plan(
                validator_id=validator_id,
                binding=binding,
            )
        )
    )
    receipt = writer.evidence.finalize(
        canonical_bytes(
            build_repair_candidate_validation_receipt(
                validator_id=validator_id,
                validation_plan_hash=plan.sha256,
                protocol=protocol,
                result_artifact_hashes=tuple(
                    sorted(identity for _name, identity in roles)
                ),
            )
        )
    )
    candidate = writer.evidence.finalize(
        canonical_bytes(
            build_repair_candidate(
                bound_validation_observations=bound_observations,
                cause_hash=str(repair["cause_hash"]),
                changed_dimension=changed_dimension,
                explanation="evaluate the changed fixture basis",
                implementation_proof_hash=implementation_proof_hash,
                job_hash=str(job["hash"]),
                job_id=str(job["id"]),
                new_basis_hash=new_basis_hash,
                new_evidence_hashes=changed_evidence_hashes,
                previous_basis_hash=str(repair["latest_basis_hash"]),
                prior_attempt_record_id=repair["latest_attempt_record_id"],
                prior_validation_observation_head=observation_head,
                repair_axis_id=axis_id,
                repair_id=str(repair["id"]),
                reproduction_evidence_hashes=tuple(
                    opened.payload["minimum_reproduction_evidence"]
                ),
                resume_action=str(repair["resume_action"]),
                verification_evidence_hashes=(receipt.sha256,),
            )
        )
    )
    return candidate.sha256


def materialize_fixture_repair_inventory(
    writer: StateWriter,
    *,
    coverage_complete: bool,
    no_identity_preserving_repair_route_remaining: bool,
) -> str:
    """Materialize terminal authority from raw accepted-attempt inventory."""

    control = writer.read_control()
    if control is None:
        raise AssertionError("fixture control is absent")
    repair = control["scientific"]["active_repair"]
    if not isinstance(repair, dict):
        raise AssertionError("fixture Repair is absent")
    grouped: dict[tuple[str, str], list[str]] = {}
    with writer.open_stable_index() as (_stable_control, index):
        head = index.event_head(f"repair-attempt:{repair['id']}")
        if head is not None:
            for sequence in range(1, head.sequence + 1):
                attempt = index.event_record(
                    f"repair-attempt:{repair['id']}", sequence
                )
                if attempt is None:
                    raise AssertionError("fixture Repair attempt stream has a gap")
                candidate = attempt.payload.get("repair_candidate")
                if not isinstance(candidate, dict):
                    raise AssertionError("fixture attempt candidate is absent")
                key = (
                    str(candidate["repair_axis_id"]),
                    str(candidate["changed_dimension"]),
                )
                grouped.setdefault(key, []).append(attempt.record_id)

    supports: dict[tuple[str, str], str] = {}
    for axis_id, dimension in sorted(grouped):
        artifact = writer.evidence.finalize(
            canonical_bytes(
                {
                    "axis_id": axis_id,
                    "changed_dimension": dimension,
                    "schema": "engineering_repair_inventory_support_fixture.v1",
                }
            )
        )
        supports[(axis_id, dimension)] = artifact.sha256
    if not grouped:
        key = ("fixture-infeasible-route", "implementation")
        artifact = writer.evidence.finalize(
            canonical_bytes(
                {
                    "axis_id": key[0],
                    "changed_dimension": key[1],
                    "schema": "engineering_repair_inventory_support_fixture.v1",
                }
            )
        )
        supports[key] = artifact.sha256

    axes = []
    if grouped:
        for key in sorted(grouped):
            axes.append(
                {
                    "accepted_attempt_record_ids": sorted(grouped[key]),
                    "axis_id": key[0],
                    "changed_dimension": key[1],
                    "state": "attempt_failed",
                    "support_evidence_hashes": [supports[key]],
                    "value_assessment": None,
                }
            )
    else:
        key = next(iter(supports))
        axes.append(
            {
                "accepted_attempt_record_ids": [],
                "axis_id": key[0],
                "changed_dimension": key[1],
                "state": "infeasible",
                "support_evidence_hashes": [supports[key]],
                "value_assessment": None,
            }
        )
    inventory = writer.evidence.finalize(
        canonical_bytes(
            {
                "axes": axes,
                "coverage_complete": coverage_complete,
                "no_identity_preserving_repair_route_remaining": (
                    no_identity_preserving_repair_route_remaining
                ),
                "schema": "engineering_repair_inventory_facts.v1",
            }
        )
    )
    protocol = (
        EngineeringRepairFixtureValidator.protocol
        if writer.engineering_fixture
        else EngineeringRepairBoundaryFixtureValidator.protocol
    )
    validator_id = (
        EngineeringRepairFixtureValidator.validator_id
        if writer.engineering_fixture
        else EngineeringRepairBoundaryFixtureValidator.validator_id
    )
    result_artifacts = {
        f"support:{ordinal:04d}": identity
        for ordinal, identity in enumerate(sorted(supports.values()))
    }
    result_artifacts["validation_result"] = inventory.sha256
    return materialize_engineering_repair_disposition(
        writer,
        inventory_validator_id=validator_id,
        inventory_protocol=protocol,
        inventory_result_artifacts=result_artifacts,
        rationale="the complete fixture inventory has no remaining route",
        resume_condition="complete the fixture engineering failure",
    )


__all__ = [
    "materialize_fixture_repair_inventory",
    "repair_candidate_fixture",
]
