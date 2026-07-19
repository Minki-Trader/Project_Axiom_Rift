from __future__ import annotations

import pytest

from axiom_rift.operations.prospective_pair_status_projection_validation import (
    RUNNING_JOB_SOURCE_SHA256,
    projection_verification_manifest,
)
from axiom_rift.operations.repair_semantic_equivalence import (
    RepairSemanticEquivalenceError,
)
from axiom_rift.operations.running_job import (
    _require_passed_prospective_pair_status_correction_facts,
)
from axiom_rift.research.sleeve_exposure_cap_risk_trace import (
    _intent_observation,
)


TRACE_PAIR = {
    "new_artifact_hash": (
        "d21ad03596d7aa8b85eae0de59bee15c9f5412d70dada83ebdd19297dc614b8c"
    ),
    "old_artifact_hash": (
        "6d3109c5ad6230d6cc2dcc71c0a393c168bedf01e4fa2f274697d5dc15cd512a"
    ),
    "relative_path": "axiom_rift/research/sleeve_exposure_cap_risk_trace.py",
}


def test_mechanism_status_is_normalized_to_registered_trace_status() -> None:
    observation = _intent_observation(
        (
            "router",
            "2024-01-02T09:00:00",
            "2024-01-02T09:05:00",
            "2024-01-02T09:10:00",
            1,
            "gross_exposure_cap_blocked",
        ),
        configuration_id="subject",
        executable_id="executable:" + "0" * 64,
        fold_id="fold-test",
    )
    assert observation["status"] == "risk_policy_skipped"


def test_projection_verification_rejects_tampered_status_fact() -> None:
    verification = projection_verification_manifest()
    assert verification["running_job_source_sha256"] == RUNNING_JOB_SOURCE_SHA256
    binding = {
        "changed_source_pair_bindings": [dict(TRACE_PAIR)],
        "claims": ["claim"],
        "new_implementation_identity": "2" * 64,
        "old_implementation_identity": "1" * 64,
        "repair_id": "repair:" + "3" * 64,
        "result_manifest_hash": "4" * 64,
        "validation_plan_hash": "5" * 64,
        "validator_id": (
            "validator:b4be337629711282d7c6c6f3deb3de23736163bbce56ce3a523f8608e156c8e4"
        ),
    }
    facts = {
        "changed_source_pair": dict(TRACE_PAIR),
        "covered_surface_ids": ["claim"],
        "new_implementation_identity": "2" * 64,
        "old_implementation_identity": "1" * 64,
        "repair_id": "repair:" + "3" * 64,
        "result_manifest_hash": "4" * 64,
        "schema": "prospective_pair_status_encoding_correction_facts.v1",
        "source_status": "gross_exposure_cap_blocked",
        "trace_status": "gross_exposure_cap_blocked",
        "validation_plan_hash": "5" * 64,
    }
    with pytest.raises(RepairSemanticEquivalenceError):
        _require_passed_prospective_pair_status_correction_facts(
            binding=binding,
            facts=facts,
        )
