from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
import axiom_rift.operations.repair_semantic_change_authority as authority


MISSION_ID = "MIS-SEMANTIC-AUTHORITY"
REPAIR_ID = "repair:" + "1" * 64
JOB_HASH = "2" * 64
JOB_ID = "job:" + JOB_HASH
CURRENT_BASIS_HASH = "3" * 64
IMPLEMENTATION_IDENTITY = "4" * 64
ATTEMPT_HEAD = "5" * 64
OBSERVATION_HEAD = {
    "fingerprint": "6" * 64,
    "record_id": "7" * 64,
    "sequence": 2,
}
IMPLEMENTATION_PROTOCOL = "python.semantic-authority.fixture.v1"


def _executable(threshold: int) -> ExecutableSpec:
    component = ComponentSpec(
        display_name="semantic authority component",
        protocol="model.semantic-authority.fixture.v1",
        implementation="python.fixture@sha256:" + "8" * 64,
        spec={"threshold": threshold},
    )
    return ExecutableSpec(
        display_name="semantic authority executable",
        components=(component,),
        parameters={"threshold": threshold},
        data_contract="observed.fixture.v1",
        split_contract="walk_forward.fixture.v1",
        clock_contract="decision_bar_close.fixture.v1",
        cost_contract="spread_and_slippage.fixture.v1",
        engine_contract="python.fixture.v1",
    )


def _job_spec(executable_id: str) -> dict[str, object]:
    return {
        "callable_identity": "axiom.fixture.semantic_authority.v1",
        "evidence_subject": {"id": executable_id, "kind": "Executable"},
        "expected_outputs": ["local/jobs/semantic/result.json"],
        "implementation_identity": IMPLEMENTATION_IDENTITY,
        "input_hashes": ["9" * 64],
        "output_classes": {
            "local/jobs/semantic/result.json": "scientific"
        },
        "resume_action": "resume_semantic_authority_fixture",
        "scientific_binding": {
            "dimensions": ["net_return"],
            "evidence_depth": "development",
            "planned_claims": ["claim.semantic-authority.fixture"],
        },
    }


def _authority_kwargs(
    *,
    current_job_spec: dict[str, object],
    current_executable: ExecutableSpec,
    successor_artifact: dict[str, object],
) -> dict[str, object]:
    return {
        "accepted_attempt_head_record_id": ATTEMPT_HEAD,
        "current_basis_hash": CURRENT_BASIS_HASH,
        "current_executable_id": current_executable.identity,
        "current_executable_manifest": current_executable.to_identity_payload(),
        "current_implementation_identity": IMPLEMENTATION_IDENTITY,
        "current_implementation_protocol": IMPLEMENTATION_PROTOCOL,
        "current_job_spec": current_job_spec,
        "job_hash": JOB_HASH,
        "job_id": JOB_ID,
        "mission_id": MISSION_ID,
        "proposed_successor_artifact": successor_artifact,
        "repair_id": REPAIR_ID,
        "repair_validation_observation_head": OBSERVATION_HEAD,
    }


def _changed_fixture() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    current_executable = _executable(1)
    proposed_executable = _executable(2)
    current_spec = _job_spec(current_executable.identity)
    proposed_spec = _job_spec(proposed_executable.identity)
    successor = authority.build_semantic_change_successor_artifact(
        successor_scope="executable",
        job_spec=proposed_spec,
        executable_manifest=proposed_executable.to_identity_payload(),
        implementation_protocol=IMPLEMENTATION_PROTOCOL,
    )
    kwargs = _authority_kwargs(
        current_job_spec=current_spec,
        current_executable=current_executable,
        successor_artifact=successor,
    )
    proposal = authority.build_semantic_change_proposal(**kwargs)
    return kwargs, proposal, successor


def test_derives_exact_surface_pairs_from_two_independent_inventories() -> None:
    kwargs, proposal, successor = _changed_fixture()
    original = authority.derive_semantic_surface_inventory
    with patch.object(
        authority,
        "derive_semantic_surface_inventory",
        wraps=original,
    ) as derive:
        case = authority.derive_semantic_change_case(
            proposal=proposal,
            **kwargs,
        )
    assert derive.call_count == 2
    assert derive.call_args_list[0].kwargs["job_spec"] == kwargs[
        "current_job_spec"
    ]
    assert derive.call_args_list[1].kwargs["job_spec"] == successor["job_spec"]

    current_authority = proposal["current_authority"]
    assert current_authority["implementation_identity"] == (
        IMPLEMENTATION_IDENTITY
    )
    assert current_authority["job_spec_sha256"] == sha256(
        canonical_bytes(kwargs["current_job_spec"])
    ).hexdigest()
    assert current_authority["executable_manifest_sha256"] == sha256(
        canonical_bytes(kwargs["current_executable_manifest"])
    ).hexdigest()
    assert current_authority["implementation_protocol_sha256"] == sha256(
        canonical_bytes(IMPLEMENTATION_PROTOCOL)
    ).hexdigest()
    assert proposal["successor_scope"] == "executable"
    assert case["successor_scope"] == "executable"
    assert case["current_authority"] == current_authority
    assert case["changed_surfaces"]

    facts = authority.semantic_change_facts(
        case,
        proposal=proposal,
        **kwargs,
    )
    assert facts == {
        "changed_surface_id_pairs": [
            {
                "current_surface_id": item["current_surface_id"],
                "path": item["path"],
                "proposed_surface_id": item["proposed_surface_id"],
            }
            for item in case["changed_surfaces"]
        ],
        "changed_surface_paths": [
            item["path"] for item in case["changed_surfaces"]
        ],
        "this_correction_changes_protected_semantics": True,
    }
    assert {
        "identity_preservation_possible",
        "no_route_remaining",
        "semantic_change_necessary",
    }.isdisjoint(facts)

    assert authority.normalize_semantic_change_proposal(
        canonical_bytes(proposal),
        **kwargs,
    ) == proposal
    assert authority.normalize_semantic_change_case(
        canonical_bytes(case),
        proposal=canonical_bytes(proposal),
        **kwargs,
    ) == case


def test_no_change_is_not_positive_semantic_change_authority() -> None:
    current_executable = _executable(1)
    current_spec = _job_spec(current_executable.identity)
    successor = authority.build_semantic_change_successor_artifact(
        successor_scope="executable",
        job_spec=deepcopy(current_spec),
        executable_manifest=current_executable.to_identity_payload(),
        implementation_protocol=IMPLEMENTATION_PROTOCOL,
    )
    kwargs = _authority_kwargs(
        current_job_spec=current_spec,
        current_executable=current_executable,
        successor_artifact=successor,
    )
    proposal = authority.build_semantic_change_proposal(**kwargs)
    with pytest.raises(
        authority.RepairSemanticChangeAuthorityError,
        match="changes no protected semantic surface",
    ):
        authority.derive_semantic_change_case(
            proposal=proposal,
            **kwargs,
        )


@pytest.mark.parametrize("path_attack", ["omit", "extra"])
def test_proposed_path_inventory_omission_or_addition_fails_closed(
    path_attack: str,
) -> None:
    current_executable = _executable(1)
    current_spec = _job_spec(current_executable.identity)
    proposed_spec = deepcopy(current_spec)
    if path_attack == "omit":
        proposed_spec.pop("scientific_binding")
    else:
        proposed_spec["runtime_binding"] = {
            "planned_materialization_cases": ["fixture.runtime.extra"]
        }
    successor = authority.build_semantic_change_successor_artifact(
        successor_scope="executable",
        job_spec=proposed_spec,
        executable_manifest=current_executable.to_identity_payload(),
        implementation_protocol=IMPLEMENTATION_PROTOCOL,
    )
    kwargs = _authority_kwargs(
        current_job_spec=current_spec,
        current_executable=current_executable,
        successor_artifact=successor,
    )
    proposal = authority.build_semantic_change_proposal(**kwargs)
    with pytest.raises(
        authority.RepairSemanticChangeAuthorityError,
        match="omits or adds a protected semantic surface path",
    ):
        authority.derive_semantic_change_case(
            proposal=proposal,
            **kwargs,
        )


def test_case_path_omission_and_extra_path_are_rederived_and_rejected() -> None:
    kwargs, proposal, _successor = _changed_fixture()
    case = authority.derive_semantic_change_case(
        proposal=proposal,
        **kwargs,
    )

    omitted = deepcopy(case)
    omitted["changed_surfaces"] = omitted["changed_surfaces"][1:]
    with pytest.raises(authority.RepairSemanticChangeAuthorityError):
        authority.normalize_semantic_change_case(
            omitted,
            proposal=proposal,
            **kwargs,
        )

    extra = deepcopy(case)
    extra["changed_surfaces"].append(
        {
            "category": "scientific",
            "current_surface_id": "repair-surface:" + "a" * 64,
            "path": "caller.injected.path",
            "proposed_surface_id": "repair-surface:" + "b" * 64,
        }
    )
    with pytest.raises(authority.RepairSemanticChangeAuthorityError):
        authority.normalize_semantic_change_case(
            extra,
            proposal=proposal,
            **kwargs,
        )


def test_caller_labels_and_noncanonical_documents_cannot_create_facts() -> None:
    kwargs, proposal, successor = _changed_fixture()
    case = authority.derive_semantic_change_case(
        proposal=proposal,
        **kwargs,
    )

    injected_successor = deepcopy(successor)
    injected_successor["changed_dimensions"] = ["scientific_semantics"]
    with pytest.raises(authority.RepairSemanticChangeAuthorityError):
        authority.normalize_semantic_change_successor_artifact(
            injected_successor
        )

    injected_proposal = deepcopy(proposal)
    injected_proposal["protected_semantic_dimensions"] = ["claim"]
    with pytest.raises(authority.RepairSemanticChangeAuthorityError):
        authority.normalize_semantic_change_proposal(
            injected_proposal,
            **kwargs,
        )

    injected_case = deepcopy(case)
    injected_case["semantic_change_necessary"] = True
    with pytest.raises(authority.RepairSemanticChangeAuthorityError):
        authority.semantic_change_facts(
            injected_case,
            proposal=proposal,
            **kwargs,
        )

    noncanonical = json.dumps(proposal, indent=2, sort_keys=True).encode("ascii")
    with pytest.raises(
        authority.RepairSemanticChangeAuthorityError,
        match="is not canonical",
    ):
        authority.normalize_semantic_change_proposal(
            noncanonical,
            **kwargs,
        )


def test_exact_current_and_successor_bindings_cannot_be_replayed() -> None:
    kwargs, proposal, successor = _changed_fixture()

    wrong_basis = deepcopy(proposal)
    wrong_basis["current_authority"]["current_basis_hash"] = "c" * 64
    with pytest.raises(
        authority.RepairSemanticChangeAuthorityError,
        match="differs from exact current authority",
    ):
        authority.normalize_semantic_change_proposal(
            wrong_basis,
            **kwargs,
        )

    changed_successor = deepcopy(successor)
    changed_successor["implementation_protocol"] = (
        "python.semantic-authority.fixture.v2"
    )
    replayed_kwargs = dict(kwargs)
    replayed_kwargs["proposed_successor_artifact"] = changed_successor
    with pytest.raises(
        authority.RepairSemanticChangeAuthorityError,
        match="successor artifact",
    ):
        authority.normalize_semantic_change_proposal(
            proposal,
            **replayed_kwargs,
        )


def test_successor_scope_is_bound_to_the_proposed_subject() -> None:
    current_executable = _executable(1)
    current_spec = _job_spec(current_executable.identity)
    proposed_spec = deepcopy(current_spec)
    proposed_spec["evidence_subject"] = {
        "id": "STU-SEMANTIC-SUCCESSOR",
        "kind": "Study",
    }
    successor = authority.build_semantic_change_successor_artifact(
        successor_scope="study",
        job_spec=proposed_spec,
        executable_manifest=current_executable.to_identity_payload(),
        implementation_protocol=IMPLEMENTATION_PROTOCOL,
    )
    kwargs = _authority_kwargs(
        current_job_spec=current_spec,
        current_executable=current_executable,
        successor_artifact=successor,
    )
    proposal = authority.build_semantic_change_proposal(**kwargs)
    case = authority.derive_semantic_change_case(
        proposal=proposal,
        **kwargs,
    )
    assert proposal["successor_scope"] == "study"
    assert case["successor_scope"] == "study"

    mismatched = deepcopy(successor)
    mismatched["successor_scope"] = "executable"
    with pytest.raises(
        authority.RepairSemanticChangeAuthorityError,
        match="subject differs from successor_scope",
    ):
        authority.normalize_semantic_change_successor_artifact(mismatched)
