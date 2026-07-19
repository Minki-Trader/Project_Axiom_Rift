from __future__ import annotations

from hashlib import sha256

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.operations.scientific_protocol_repair_inventory import (
    scientific_protocol_successor_inventory,
)
from axiom_rift.operations.validation import EvidenceValidationError


CALLABLE = "fixture.scientific_protocol_job.v1"
PROTOCOL = "python.source.scientific_protocol_fixture.v1"


def _executable(engine: str) -> ExecutableSpec:
    component = ComponentSpec(
        display_name="fixture component",
        protocol="fixture.component.v1",
        implementation="fixture.component.impl.v1",
        spec={"parameter": 1},
    )
    return ExecutableSpec(
        display_name="fixture executable",
        components=(component,),
        parameters={"engine": engine},
        data_contract="data:fixture",
        split_contract="split:fixture",
        clock_contract="clock:fixture",
        cost_contract="cost:fixture",
        engine_contract=engine,
    )


def _implementation(fill: str) -> tuple[dict[str, object], str]:
    value = {
        "artifact_hashes": [fill * 64],
        "callable_identity": CALLABLE,
        "protocol": PROTOCOL,
        "schema": "job_implementation_evidence.v1",
    }
    return value, sha256(canonical_bytes(value)).hexdigest()


def _fixture() -> dict[str, object]:
    current_executable = _executable("engine:current")
    proposed_executable = _executable("engine:corrected")
    current_implementation, current_identity = _implementation("1")
    proposed_implementation, proposed_identity = _implementation("2")
    current_spec = {
        "callable_identity": CALLABLE,
        "evidence_subject": {
            "kind": "Executable",
            "id": current_executable.identity,
        },
        "implementation_identity": current_identity,
        "input_hashes": ["3" * 64],
        "scientific_binding": {
            "validation_plan_hash": "4" * 64,
            "validator_id": "validator:" + "5" * 64,
        },
    }
    proposed_spec = {
        **current_spec,
        "evidence_subject": {
            "kind": "Executable",
            "id": proposed_executable.identity,
        },
        "implementation_identity": proposed_identity,
        "input_hashes": ["6" * 64],
        "scientific_binding": {
            "validation_plan_hash": "7" * 64,
            "validator_id": "validator:" + "5" * 64,
        },
    }
    support = {
        name: str(index) * 64
        for index, name in enumerate(
            (
                "current_executable_manifest",
                "current_implementation_manifest",
                "current_job_spec",
                "proposed_executable_manifest",
                "proposed_implementation_manifest",
                "proposed_job_spec",
            ),
            start=1,
        )
    }
    return {
        "current_executable_manifest": current_executable.to_identity_payload(),
        "current_implementation_manifest": current_implementation,
        "current_job_spec": current_spec,
        "proposed_executable_manifest": proposed_executable.to_identity_payload(),
        "proposed_implementation_manifest": proposed_implementation,
        "proposed_job_spec": proposed_spec,
        "support_hashes": support,
    }


def test_inventory_derives_input_infeasibility_and_semantic_conflict() -> None:
    result = scientific_protocol_successor_inventory(**_fixture())
    assert result["coverage_complete"] is True
    assert result["no_identity_preserving_repair_route_remaining"] is True
    assert [item["state"] for item in result["axes"]] == [
        "infeasible",
        "semantic_conflict",
    ]


def test_inventory_rejects_same_scientific_plan() -> None:
    fixture = _fixture()
    fixture["proposed_job_spec"]["scientific_binding"] = dict(
        fixture["current_job_spec"]["scientific_binding"]
    )
    with pytest.raises(EvidenceValidationError, match="protected inputs"):
        scientific_protocol_successor_inventory(**fixture)
