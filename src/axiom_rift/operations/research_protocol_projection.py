"""Authenticated projection of the active prospective research protocol.

Replay implementation admission is a capability, not a cached boolean.  It
must name the exact protocol activation that is still the current stream head
under the current authority manifest.  Keeping this read-only check outside
``StateWriter`` lets Study open, legacy recertification, trial registration,
and Job declaration consume one invariant without duplicating it.
"""

from __future__ import annotations

from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.research.protocol import (
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


RESEARCH_PROTOCOL_STREAM = "research-protocol:scientific"


class ResearchProtocolProjectionError(RuntimeError):
    """The prospective research-protocol authority is absent or malformed."""


def require_current_research_protocol_activation(
    index: LocalIndex | LocalIndexView,
    *,
    authority_manifest_digest: str,
) -> IndexRecord:
    """Return the exact current v2 activation for one authority manifest."""

    if (
        type(authority_manifest_digest) is not str
        or len(authority_manifest_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in authority_manifest_digest
        )
    ):
        raise ResearchProtocolProjectionError(
            "research protocol authority manifest digest is malformed"
        )
    head = index.event_head(RESEARCH_PROTOCOL_STREAM)
    record = (
        None
        if head is None
        else index.get(head.record_kind, head.record_id)
    )
    try:
        activation = (
            None
            if record is None
            else ResearchProtocolActivation(
                protocol=ResearchProtocol(record.payload.get("protocol")),
                validator_id=record.payload.get("validator_id"),
                authority_manifest_digest=record.payload.get(
                    "authority_manifest_digest"
                ),
                audit_artifact_hash=record.payload.get("audit_artifact_hash"),
            )
        )
    except (TypeError, ValueError):
        activation = None
    if (
        head is None
        or record is None
        or activation is None
        or head.record_kind != "research-protocol-activation"
        or record.kind != "research-protocol-activation"
        or record.record_id != activation.identity
        or record.record_id != head.record_id
        or record.subject != "ProjectGoal:OPERATING_DIRECTION.md"
        or record.status != "active"
        or record.fingerprint
        != activation.identity.removeprefix("research-protocol:")
        or record.event_stream != RESEARCH_PROTOCOL_STREAM
        or record.event_sequence != head.sequence
        or record.payload.get("ordinal") != head.sequence
        or record.payload.get("scientific_trial_delta") != 0
        or activation.protocol
        is not ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2
        or activation.validator_id
        != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        or activation.authority_manifest_digest != authority_manifest_digest
    ):
        raise ResearchProtocolProjectionError(
            "current prospective research protocol is absent, stale, or malformed"
        )
    try:
        event_kind, result = require_same_event_operation_result(
            index,
            record=record,
            expected_event_kinds=frozenset({"research_protocol_activated"}),
        )
    except RecordedTransitionAuthorityError as exc:
        raise ResearchProtocolProjectionError(
            "current research protocol lacks same-event Writer authority"
        ) from exc
    if (
        event_kind != "research_protocol_activated"
        or result.get("activation_record_id") != record.record_id
        or result.get("ordinal") != head.sequence
        or result.get("protocol") != activation.protocol.value
        or result.get("trial_delta") != 0
        or result.get("validator_id") != activation.validator_id
    ):
        raise ResearchProtocolProjectionError(
            "current research protocol Writer result is malformed"
        )
    return record


__all__ = [
    "RESEARCH_PROTOCOL_STREAM",
    "ResearchProtocolProjectionError",
    "require_current_research_protocol_activation",
]
