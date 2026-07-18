from __future__ import annotations

import pytest

from axiom_rift.research.axis_protocol_revision import (
    AXIS_PROTOCOL_REVISION_SCHEMA,
    AXIS_PROTOCOL_REVISION_SCHEMA_V2,
    AXIS_PROTOCOL_REVISION_SCHEMA_V3,
    AxisProtocolRevisionProposal,
    AxisProtocolRevisionReason,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


def _lineage() -> SemanticQuestionLineageProposal:
    return SemanticQuestionLineageProposal(
        predecessor_study_id="STU-PROTOCOL-PREDECESSOR",
        successor_study_id="STU-PROTOCOL-SUCCESSOR",
        predecessor_core_id="semantic-question-core:" + "1" * 64,
        successor_core_id="semantic-question-core:" + "1" * 64,
        relation=SemanticQuestionRelation.CONTINUATION,
        rationale="retain the same question under one corrected protocol",
        basis_record_ids=("study-open:STU-PROTOCOL-PREDECESSOR",),
    )


def _common() -> dict[str, object]:
    return {
        "mission_id": "MIS-PROTOCOL",
        "axis_id": "axis-protocol",
        "predecessor_axis_identity": "axis:" + "2" * 64,
        "successor_axis_identity": "axis:" + "3" * 64,
        "mechanism_family": "same-mechanism",
        "predecessor_architecture_family": "architecture-family:" + "4" * 64,
        "successor_architecture_family": "architecture-family:" + "5" * 64,
        "replay_obligation_id": "historical-replay-obligation:" + "6" * 64,
        "semantic_question_lineage": _lineage(),
    }


def test_v1_completion_invalidation_payload_remains_byte_compatible() -> None:
    proposal = AxisProtocolRevisionProposal(
        **_common(),
        satisfaction_invalidation_record_id=(
            "historical-replay-satisfaction-invalidation:" + "7" * 64
        ),
        reason_code=AxisProtocolRevisionReason.COMPLETION_VALIDITY_INVALIDATED,
        reason="the prior completion protocol was invalidated",
    )
    payload = proposal.to_identity_payload()

    assert payload["schema"] == AXIS_PROTOCOL_REVISION_SCHEMA
    assert "scientific_change_return_record_id" not in payload
    assert proposal.authority_kind == (
        "historical-replay-satisfaction-invalidation"
    )
    assert AxisProtocolRevisionProposal.from_mapping(payload) == proposal


def test_v2_scientific_change_return_is_distinct_typed_authority() -> None:
    return_id = "historical-replay-scientific-change-return:" + "8" * 64
    proposal = AxisProtocolRevisionProposal(
        **_common(),
        satisfaction_invalidation_record_id=None,
        scientific_change_return_record_id=return_id,
        reason_code=(
            AxisProtocolRevisionReason.ENGINEERING_REQUIRES_SCIENTIFIC_CHANGE
        ),
        reason="the prior Study requires a distinct feasible scientific protocol",
    )
    payload = proposal.to_identity_payload()

    assert payload["schema"] == AXIS_PROTOCOL_REVISION_SCHEMA_V2
    assert "satisfaction_invalidation_record_id" not in payload
    assert proposal.authority_kind == (
        "historical-replay-scientific-change-return"
    )
    assert proposal.authority_record_id == return_id
    assert AxisProtocolRevisionProposal.from_mapping(payload) == proposal


def test_scientific_change_revision_rejects_mixed_authority() -> None:
    with pytest.raises(ValueError, match="cannot bind a satisfaction"):
        AxisProtocolRevisionProposal(
            **_common(),
            satisfaction_invalidation_record_id=(
                "historical-replay-satisfaction-invalidation:" + "7" * 64
            ),
            scientific_change_return_record_id=(
                "historical-replay-scientific-change-return:" + "8" * 64
            ),
            reason_code=(
                AxisProtocolRevisionReason.ENGINEERING_REQUIRES_SCIENTIFIC_CHANGE
            ),
            reason="reject mixed protocol authority",
        )


def test_v3_initial_historical_completion_invalidation_is_distinct() -> None:
    invalidation_id = (
        "historical-scientific-validity-invalidation:" + "9" * 64
    )
    proposal = AxisProtocolRevisionProposal(
        **_common(),
        satisfaction_invalidation_record_id=None,
        completion_validity_invalidation_record_id=invalidation_id,
        reason_code=(
            AxisProtocolRevisionReason.HISTORICAL_COMPLETION_VALIDITY_INVALIDATED
        ),
        reason=(
            "the original completion used an invalid decision-time input and "
            "requires a corrected prospective protocol"
        ),
    )
    payload = proposal.to_identity_payload()

    assert payload["schema"] == AXIS_PROTOCOL_REVISION_SCHEMA_V3
    assert "satisfaction_invalidation_record_id" not in payload
    assert "scientific_change_return_record_id" not in payload
    assert proposal.authority_kind == (
        "historical-scientific-validity-invalidation"
    )
    assert proposal.authority_record_id == invalidation_id
    assert AxisProtocolRevisionProposal.from_mapping(payload) == proposal


def test_historical_completion_revision_rejects_mixed_authority() -> None:
    with pytest.raises(ValueError, match="cannot bind a satisfaction"):
        AxisProtocolRevisionProposal(
            **_common(),
            satisfaction_invalidation_record_id=(
                "historical-replay-satisfaction-invalidation:" + "7" * 64
            ),
            completion_validity_invalidation_record_id=(
                "historical-scientific-validity-invalidation:" + "9" * 64
            ),
            reason_code=(
                AxisProtocolRevisionReason.HISTORICAL_COMPLETION_VALIDITY_INVALIDATED
            ),
            reason="reject mixed historical completion authority",
        )
