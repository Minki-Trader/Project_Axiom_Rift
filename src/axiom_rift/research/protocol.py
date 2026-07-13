"""Durable activation records for prospective research protocols."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from axiom_rift.core.identity import canonical_digest


class ResearchProtocol(str, Enum):
    SCIENTIFIC_ADJUDICATION_V2 = "scientific_adjudication_v2"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchProtocolActivation:
    protocol: ResearchProtocol
    validator_id: str
    authority_manifest_digest: str
    audit_artifact_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, ResearchProtocol):
            raise TypeError("protocol must be a ResearchProtocol")
        validator = _ascii("validator_id", self.validator_id)
        if not validator.startswith("validator:"):
            raise ValueError("validator_id must be a validator identity")
        _digest("validator digest", validator.removeprefix("validator:"))
        _digest("authority_manifest_digest", self.authority_manifest_digest)
        _digest("audit_artifact_hash", self.audit_artifact_hash)

    @property
    def identity(self) -> str:
        return "research-protocol:" + canonical_digest(
            domain="research-protocol-activation",
            payload=self.to_identity_payload(),
        )

    def to_identity_payload(self) -> dict[str, str]:
        return {
            "audit_artifact_hash": self.audit_artifact_hash,
            "authority_manifest_digest": self.authority_manifest_digest,
            "protocol": self.protocol.value,
            "schema": "research_protocol_activation.v1",
            "validator_id": self.validator_id,
        }


__all__ = [
    "ResearchProtocol",
    "ResearchProtocolActivation",
]
