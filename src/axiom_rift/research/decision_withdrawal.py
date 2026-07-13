"""Typed evidence for withdrawing one accepted but unstarted Decision."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.audit_report import require_ascii_finding_block


WITHDRAWAL_MANIFEST_SCHEMA = "portfolio_decision_withdrawal_manifest.v1"


class PortfolioDecisionWithdrawalReason(str, Enum):
    SOURCE_AUTHORITY_INVALIDATED = "source_authority_invalidated"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identity(name: str, value: object, *, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise ValueError(f"{name} must use the {prefix!r} namespace")
    _digest(f"{name} digest", text.removeprefix(prefix))
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioDecisionWithdrawalManifest:
    report_artifact_hash: str
    report_finding_id: str
    decision_id: str
    portfolio_snapshot_id: str
    target_axis_id: str
    target_axis_identity: str
    baseline_executable_id: str
    source_contract_id: str
    source_state_record_id: str
    reason_code: PortfolioDecisionWithdrawalReason
    reason: str

    def __post_init__(self) -> None:
        _digest("report_artifact_hash", self.report_artifact_hash)
        _ascii("report_finding_id", self.report_finding_id)
        _identity("decision_id", self.decision_id, prefix="decision:")
        _identity(
            "portfolio_snapshot_id",
            self.portfolio_snapshot_id,
            prefix="portfolio:",
        )
        _ascii("target_axis_id", self.target_axis_id)
        _identity("target_axis_identity", self.target_axis_identity, prefix="axis:")
        _identity(
            "baseline_executable_id",
            self.baseline_executable_id,
            prefix="executable:",
        )
        _identity("source_contract_id", self.source_contract_id, prefix="source:")
        _digest("source_state_record_id", self.source_state_record_id)
        if not isinstance(self.reason_code, PortfolioDecisionWithdrawalReason):
            raise TypeError("reason_code must be a PortfolioDecisionWithdrawalReason")
        _ascii("withdrawal reason", self.reason)

    @property
    def identity(self) -> str:
        return "portfolio-decision-withdrawal-manifest:" + canonical_digest(
            domain="portfolio-decision-withdrawal-manifest",
            payload=self.to_identity_payload(),
        )

    def require_report(self, document: bytes) -> None:
        require_ascii_finding_block(
            document,
            finding_id=self.report_finding_id,
            required_fragments=(
                self.source_contract_id,
                f"audited head {self.source_state_record_id}",
            ),
        )

    def to_identity_payload(self) -> dict[str, str]:
        return {
            "baseline_executable_id": self.baseline_executable_id,
            "decision_id": self.decision_id,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "reason": self.reason,
            "reason_code": self.reason_code.value,
            "report_artifact_hash": self.report_artifact_hash,
            "report_finding_id": self.report_finding_id,
            "schema": WITHDRAWAL_MANIFEST_SCHEMA,
            "source_contract_id": self.source_contract_id,
            "source_state_record_id": self.source_state_record_id,
            "target_axis_id": self.target_axis_id,
            "target_axis_identity": self.target_axis_identity,
        }

    @classmethod
    def from_mapping(
        cls,
        value: object,
    ) -> PortfolioDecisionWithdrawalManifest:
        fields = {
            "baseline_executable_id",
            "decision_id",
            "portfolio_snapshot_id",
            "reason",
            "reason_code",
            "report_artifact_hash",
            "report_finding_id",
            "schema",
            "source_contract_id",
            "source_state_record_id",
            "target_axis_id",
            "target_axis_identity",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("Portfolio Decision withdrawal manifest schema is invalid")
        if value["schema"] != WITHDRAWAL_MANIFEST_SCHEMA:
            raise ValueError("Portfolio Decision withdrawal manifest is unsupported")
        return cls(
            report_artifact_hash=value["report_artifact_hash"],  # type: ignore[arg-type]
            report_finding_id=value["report_finding_id"],  # type: ignore[arg-type]
            decision_id=value["decision_id"],  # type: ignore[arg-type]
            portfolio_snapshot_id=value["portfolio_snapshot_id"],  # type: ignore[arg-type]
            target_axis_id=value["target_axis_id"],  # type: ignore[arg-type]
            target_axis_identity=value["target_axis_identity"],  # type: ignore[arg-type]
            baseline_executable_id=value["baseline_executable_id"],  # type: ignore[arg-type]
            source_contract_id=value["source_contract_id"],  # type: ignore[arg-type]
            source_state_record_id=value["source_state_record_id"],  # type: ignore[arg-type]
            reason_code=PortfolioDecisionWithdrawalReason(value["reason_code"]),
            reason=value["reason"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, document: bytes) -> PortfolioDecisionWithdrawalManifest:
        return cls.from_mapping(parse_canonical(document))


__all__ = [
    "PortfolioDecisionWithdrawalManifest",
    "PortfolioDecisionWithdrawalReason",
    "WITHDRAWAL_MANIFEST_SCHEMA",
]
