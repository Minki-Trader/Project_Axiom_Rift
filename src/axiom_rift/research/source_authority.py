"""Typed, additive invalidation of legacy external-source authority.

Source eligibility normally advances from evidence produced by a source Job.
An exhaustive audit can instead discover that an already-active identity never
had the point-in-time authority its historical receipt claimed.  This module
describes that correction without rewriting the old receipt or turning an
engineering/source defect into scientific evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Sequence

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.audit_report import require_ascii_finding_block


AUDIT_MANIFEST_SCHEMA = "source_authority_audit_manifest.v1"
AUTHORITY_LATCH_SCHEMA = "source_authority_latch.v1"
AUTHORITY_LATCH_STATUS = "unresolved"
AUTHORITY_RECOVERY_POLICY = "new_source_contract_only"
AUTHORITY_TRANSITION_EVIDENCE = "authority_invalidation"
SOURCE_REPLACEMENT_LINEAGE_SCHEMA = "source_replacement_lineage.v1"
SOURCE_REPLACEMENT_CAPABILITY_SET_SCHEMA = (
    "source_replacement_capability_set.v1"
)


class SourceAuthoritySurface(str, Enum):
    AVAILABILITY = "availability"
    CLOCK = "clock"
    FIELD = "field"
    IMPLEMENTATION = "implementation"
    MAPPING = "mapping"
    SCHEMA = "schema"


class SourceAuthorityReason(str, Enum):
    IMPLEMENTATION_IDENTITY_UNPROVEN = "implementation_identity_unproven"
    POINT_IN_TIME_AUTHORITY_UNPROVEN = "point_in_time_authority_unproven"
    RUNTIME_SEMANTICS_DRIFTED = "runtime_semantics_drifted"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _prefixed_digest(name: str, value: object, *, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise ValueError(f"{name} must use the {prefix!r} namespace")
    _digest(f"{name} digest", text.removeprefix(prefix))
    return text


def _timestamp(name: str, value: object) -> str:
    observed = _ascii(name, value)
    try:
        parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return observed


def _exact_mapping(
    name: str,
    value: object,
    *,
    fields: frozenset[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} has an invalid schema")
    return value


def source_replacement_capability_id(
    *,
    mission_id: str,
    original_axis_id: str,
    original_axis_identity: str,
    invalidation_id: str,
    invalidated_source_contract_id: str,
) -> str:
    """Identify the exact recovery capability an external outage may block."""

    _ascii("source replacement capability Mission id", mission_id)
    _ascii("source replacement capability axis id", original_axis_id)
    _prefixed_digest(
        "source replacement capability axis identity",
        original_axis_identity,
        prefix="axis:",
    )
    _prefixed_digest(
        "source replacement capability invalidation",
        invalidation_id,
        prefix="source-authority-invalidation:",
    )
    _prefixed_digest(
        "source replacement capability invalidated contract",
        invalidated_source_contract_id,
        prefix="source:",
    )
    return "source-replacement-capability:" + canonical_digest(
        domain="source-replacement-capability",
        payload={
            "invalidation_id": invalidation_id,
            "invalidated_source_contract_id": invalidated_source_contract_id,
            "mission_id": mission_id,
            "original_axis_id": original_axis_id,
            "original_axis_identity": original_axis_identity,
        },
    )


def source_replacement_capability_set_id(
    capability_ids: Sequence[str],
) -> str:
    """Bind two or more exact source-replacement capabilities as one set.

    A genuine external outage may make several invalidated source axes
    unavailable through the same indispensable dependency.  The aggregate is
    deterministic and cannot hide a non-source blocker because the Writer
    derives every member from the current effective-axis projection.
    """

    if isinstance(capability_ids, (str, bytes)):
        raise ValueError(
            "source replacement capability set must be a sequence of identities"
        )
    typed = tuple(capability_ids)
    if len(typed) < 2 or len(typed) != len(set(typed)):
        raise ValueError(
            "source replacement capability set requires distinct multiple identities"
        )
    for capability_id in typed:
        _prefixed_digest(
            "source replacement capability set member",
            capability_id,
            prefix="source-replacement-capability:",
        )
    ordered = tuple(sorted(typed))
    return "source-replacement-capability-set:" + canonical_digest(
        domain="source-replacement-capability-set",
        payload={
            "capability_ids": list(ordered),
            "schema": SOURCE_REPLACEMENT_CAPABILITY_SET_SCHEMA,
        },
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceAuthorityAuditManifest:
    """Canonical per-source finding bound to one durable project audit report."""

    report_artifact_hash: str
    report_finding_id: str
    source_contract_id: str
    source_state_record_id: str
    surface: SourceAuthoritySurface
    reason_code: SourceAuthorityReason
    observed_defect: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        _digest("report_artifact_hash", self.report_artifact_hash)
        _ascii("report_finding_id", self.report_finding_id)
        _prefixed_digest(
            "source_contract_id", self.source_contract_id, prefix="source:"
        )
        _digest("source_state_record_id", self.source_state_record_id)
        if not isinstance(self.surface, SourceAuthoritySurface):
            raise TypeError("surface must be a SourceAuthoritySurface")
        if not isinstance(self.reason_code, SourceAuthorityReason):
            raise TypeError("reason_code must be a SourceAuthorityReason")
        _ascii("observed_defect", self.observed_defect)
        _timestamp("observed_at_utc", self.observed_at_utc)

    def finding_payload(self) -> dict[str, str]:
        return {
            "observed_at_utc": self.observed_at_utc,
            "observed_defect": self.observed_defect,
            "reason_code": self.reason_code.value,
            "source_contract_id": self.source_contract_id,
            "source_state_record_id": self.source_state_record_id,
            "surface": self.surface.value,
        }

    def to_identity_payload(self) -> dict[str, object]:
        return {
            **self.finding_payload(),
            "report_artifact_hash": self.report_artifact_hash,
            "report_finding_id": self.report_finding_id,
            "schema": AUDIT_MANIFEST_SCHEMA,
        }

    def require_report(self, document: bytes) -> None:
        """Prove that the named source and head belong to this exact finding."""

        require_ascii_finding_block(
            document,
            finding_id=self.report_finding_id,
            required_fragments=(
                self.source_contract_id,
                f"audited head {self.source_state_record_id}",
            ),
        )

    @classmethod
    def from_mapping(cls, value: object) -> SourceAuthorityAuditManifest:
        payload = _exact_mapping(
            "source authority audit manifest",
            value,
            fields=frozenset(
                {
                    "observed_at_utc",
                    "observed_defect",
                    "reason_code",
                    "report_artifact_hash",
                    "report_finding_id",
                    "schema",
                    "source_contract_id",
                    "source_state_record_id",
                    "surface",
                }
            ),
        )
        if payload["schema"] != AUDIT_MANIFEST_SCHEMA:
            raise ValueError("source authority audit manifest schema is unsupported")
        return cls(
            report_artifact_hash=payload["report_artifact_hash"],  # type: ignore[arg-type]
            report_finding_id=payload["report_finding_id"],  # type: ignore[arg-type]
            source_contract_id=payload["source_contract_id"],  # type: ignore[arg-type]
            source_state_record_id=payload["source_state_record_id"],  # type: ignore[arg-type]
            surface=SourceAuthoritySurface(payload["surface"]),
            reason_code=SourceAuthorityReason(payload["reason_code"]),
            observed_defect=payload["observed_defect"],  # type: ignore[arg-type]
            observed_at_utc=payload["observed_at_utc"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, document: bytes) -> SourceAuthorityAuditManifest:
        return cls.from_mapping(parse_canonical(document))


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceAuthorityInvalidation:
    """One exact source-state head invalidated by durable audit evidence."""

    source_contract_id: str
    source_state_record_id: str
    audit_artifact_hash: str
    surface: SourceAuthoritySurface
    reason_code: SourceAuthorityReason
    observed_defect: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        _prefixed_digest(
            "source_contract_id", self.source_contract_id, prefix="source:"
        )
        _digest("source_state_record_id", self.source_state_record_id)
        _digest("audit_artifact_hash", self.audit_artifact_hash)
        if not isinstance(self.surface, SourceAuthoritySurface):
            raise TypeError("surface must be a SourceAuthoritySurface")
        if not isinstance(self.reason_code, SourceAuthorityReason):
            raise TypeError("reason_code must be a SourceAuthorityReason")
        _ascii("observed_defect", self.observed_defect)
        _timestamp("observed_at_utc", self.observed_at_utc)

    @property
    def identity(self) -> str:
        return "source-authority-invalidation:" + canonical_digest(
            domain="source-authority-invalidation",
            payload=self.to_identity_payload(),
        )

    def drift_facts(self) -> dict[str, str]:
        return {
            "changed_surface": self.surface.value,
            "dependent_action": "suspend_performance_and_runtime_authority",
            "observed_change": self.observed_defect,
        }

    def finding_payload(self) -> dict[str, str]:
        return {
            "observed_at_utc": self.observed_at_utc,
            "observed_defect": self.observed_defect,
            "reason_code": self.reason_code.value,
            "source_contract_id": self.source_contract_id,
            "source_state_record_id": self.source_state_record_id,
            "surface": self.surface.value,
        }

    def require_manifest(self, manifest: SourceAuthorityAuditManifest) -> None:
        if not isinstance(manifest, SourceAuthorityAuditManifest):
            raise TypeError("manifest must be a SourceAuthorityAuditManifest")
        if manifest.finding_payload() != self.finding_payload():
            raise ValueError("source authority manifest does not bind the invalidation")

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "audit_artifact_hash": self.audit_artifact_hash,
            **self.finding_payload(),
            "schema": "source_authority_invalidation.v1",
        }

    @classmethod
    def from_identity_payload(
        cls, value: object
    ) -> SourceAuthorityInvalidation:
        payload = _exact_mapping(
            "source authority invalidation",
            value,
            fields=frozenset(
                {
                    "audit_artifact_hash",
                    "observed_at_utc",
                    "observed_defect",
                    "reason_code",
                    "schema",
                    "source_contract_id",
                    "source_state_record_id",
                    "surface",
                }
            ),
        )
        if payload["schema"] != "source_authority_invalidation.v1":
            raise ValueError("source authority invalidation schema is unsupported")
        return cls(
            source_contract_id=payload["source_contract_id"],  # type: ignore[arg-type]
            source_state_record_id=payload["source_state_record_id"],  # type: ignore[arg-type]
            audit_artifact_hash=payload["audit_artifact_hash"],  # type: ignore[arg-type]
            surface=SourceAuthoritySurface(payload["surface"]),
            reason_code=SourceAuthorityReason(payload["reason_code"]),
            observed_defect=payload["observed_defect"],  # type: ignore[arg-type]
            observed_at_utc=payload["observed_at_utc"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceAuthorityLatch:
    """Permanent fail-closed latch for an audit-invalidated SourceContract."""

    invalidation_id: str
    source_contract_id: str
    invalidated_source_state_record_id: str
    audit_manifest_hash: str
    report_artifact_hash: str
    report_finding_id: str
    surface: SourceAuthoritySurface
    reason_code: SourceAuthorityReason

    def __post_init__(self) -> None:
        _prefixed_digest(
            "invalidation_id",
            self.invalidation_id,
            prefix="source-authority-invalidation:",
        )
        _prefixed_digest(
            "source_contract_id", self.source_contract_id, prefix="source:"
        )
        _digest(
            "invalidated_source_state_record_id",
            self.invalidated_source_state_record_id,
        )
        _digest("audit_manifest_hash", self.audit_manifest_hash)
        _digest("report_artifact_hash", self.report_artifact_hash)
        _ascii("report_finding_id", self.report_finding_id)
        if not isinstance(self.surface, SourceAuthoritySurface):
            raise TypeError("surface must be a SourceAuthoritySurface")
        if not isinstance(self.reason_code, SourceAuthorityReason):
            raise TypeError("reason_code must be a SourceAuthorityReason")

    @classmethod
    def bind(
        cls,
        *,
        invalidation: SourceAuthorityInvalidation,
        manifest: SourceAuthorityAuditManifest,
    ) -> SourceAuthorityLatch:
        invalidation.require_manifest(manifest)
        return cls(
            invalidation_id=invalidation.identity,
            source_contract_id=invalidation.source_contract_id,
            invalidated_source_state_record_id=invalidation.source_state_record_id,
            audit_manifest_hash=invalidation.audit_artifact_hash,
            report_artifact_hash=manifest.report_artifact_hash,
            report_finding_id=manifest.report_finding_id,
            surface=invalidation.surface,
            reason_code=invalidation.reason_code,
        )

    def to_identity_payload(self) -> dict[str, str]:
        return {
            "audit_manifest_hash": self.audit_manifest_hash,
            "invalidated_source_state_record_id": self.invalidated_source_state_record_id,
            "invalidation_id": self.invalidation_id,
            "reason_code": self.reason_code.value,
            "recovery_policy": AUTHORITY_RECOVERY_POLICY,
            "report_artifact_hash": self.report_artifact_hash,
            "report_finding_id": self.report_finding_id,
            "schema": AUTHORITY_LATCH_SCHEMA,
            "source_contract_id": self.source_contract_id,
            "status": AUTHORITY_LATCH_STATUS,
            "surface": self.surface.value,
        }

    @classmethod
    def from_mapping(cls, value: object) -> SourceAuthorityLatch:
        payload = _exact_mapping(
            "source authority latch",
            value,
            fields=frozenset(
                {
                    "audit_manifest_hash",
                    "invalidated_source_state_record_id",
                    "invalidation_id",
                    "reason_code",
                    "recovery_policy",
                    "report_artifact_hash",
                    "report_finding_id",
                    "schema",
                    "source_contract_id",
                    "status",
                    "surface",
                }
            ),
        )
        if (
            payload["schema"] != AUTHORITY_LATCH_SCHEMA
            or payload["status"] != AUTHORITY_LATCH_STATUS
            or payload["recovery_policy"] != AUTHORITY_RECOVERY_POLICY
        ):
            raise ValueError("source authority latch policy is invalid")
        return cls(
            invalidation_id=payload["invalidation_id"],  # type: ignore[arg-type]
            source_contract_id=payload["source_contract_id"],  # type: ignore[arg-type]
            invalidated_source_state_record_id=payload[
                "invalidated_source_state_record_id"
            ],  # type: ignore[arg-type]
            audit_manifest_hash=payload["audit_manifest_hash"],  # type: ignore[arg-type]
            report_artifact_hash=payload["report_artifact_hash"],  # type: ignore[arg-type]
            report_finding_id=payload["report_finding_id"],  # type: ignore[arg-type]
            surface=SourceAuthoritySurface(payload["surface"]),
            reason_code=SourceAuthorityReason(payload["reason_code"]),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceReplacementLineage:
    """Additive retirement of one invalidated source axis into a new axis.

    The original Portfolio snapshot and permanent source latch remain
    untouched.  This identity only states that a distinct, eligible
    SourceContract was bound to a distinct Portfolio axis before the old axis
    stopped participating in scheduling or Mission-terminal blocker counts.
    """

    mission_id: str
    portfolio_snapshot_id: str
    original_axis_id: str
    original_axis_identity: str
    invalidation_id: str
    invalidated_source_contract_id: str
    replacement_source_contract_id: str
    replacement_source_state_record_id: str
    replacement_axis_id: str
    replacement_axis_identity: str

    def __post_init__(self) -> None:
        _ascii("source replacement Mission id", self.mission_id)
        _prefixed_digest(
            "source replacement Portfolio snapshot",
            self.portfolio_snapshot_id,
            prefix="portfolio:",
        )
        _ascii("source replacement original axis id", self.original_axis_id)
        _prefixed_digest(
            "source replacement original axis identity",
            self.original_axis_identity,
            prefix="axis:",
        )
        _prefixed_digest(
            "source replacement invalidation",
            self.invalidation_id,
            prefix="source-authority-invalidation:",
        )
        _prefixed_digest(
            "source replacement invalidated contract",
            self.invalidated_source_contract_id,
            prefix="source:",
        )
        _prefixed_digest(
            "source replacement contract",
            self.replacement_source_contract_id,
            prefix="source:",
        )
        _digest(
            "source replacement state record",
            self.replacement_source_state_record_id,
        )
        _ascii("source replacement axis id", self.replacement_axis_id)
        _prefixed_digest(
            "source replacement axis identity",
            self.replacement_axis_identity,
            prefix="axis:",
        )
        if (
            self.invalidated_source_contract_id
            == self.replacement_source_contract_id
        ):
            raise ValueError(
                "source replacement requires a distinct SourceContract identity"
            )
        if (
            self.original_axis_id == self.replacement_axis_id
            or self.original_axis_identity == self.replacement_axis_identity
        ):
            raise ValueError(
                "source replacement requires a distinct Portfolio axis"
            )

    @property
    def identity(self) -> str:
        return "source-replacement-lineage:" + canonical_digest(
            domain="source-replacement-lineage",
            payload=self.to_identity_payload(),
        )

    @property
    def capability_id(self) -> str:
        """Capability whose external absence can pause this exact recovery."""

        return source_replacement_capability_id(
            mission_id=self.mission_id,
            original_axis_id=self.original_axis_id,
            original_axis_identity=self.original_axis_identity,
            invalidation_id=self.invalidation_id,
            invalidated_source_contract_id=self.invalidated_source_contract_id,
        )

    def to_identity_payload(self) -> dict[str, str]:
        return {
            "invalidation_id": self.invalidation_id,
            "invalidated_source_contract_id": self.invalidated_source_contract_id,
            "mission_id": self.mission_id,
            "original_axis_id": self.original_axis_id,
            "original_axis_identity": self.original_axis_identity,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "replacement_axis_id": self.replacement_axis_id,
            "replacement_axis_identity": self.replacement_axis_identity,
            "replacement_source_contract_id": self.replacement_source_contract_id,
            "replacement_source_state_record_id": (
                self.replacement_source_state_record_id
            ),
            "schema": SOURCE_REPLACEMENT_LINEAGE_SCHEMA,
        }

    @classmethod
    def from_mapping(cls, value: object) -> SourceReplacementLineage:
        payload = _exact_mapping(
            "source replacement lineage",
            value,
            fields=frozenset(
                {
                    "invalidation_id",
                    "invalidated_source_contract_id",
                    "mission_id",
                    "original_axis_id",
                    "original_axis_identity",
                    "portfolio_snapshot_id",
                    "replacement_axis_id",
                    "replacement_axis_identity",
                    "replacement_source_contract_id",
                    "replacement_source_state_record_id",
                    "schema",
                }
            ),
        )
        if payload["schema"] != SOURCE_REPLACEMENT_LINEAGE_SCHEMA:
            raise ValueError("source replacement lineage schema is unsupported")
        return cls(
            mission_id=payload["mission_id"],  # type: ignore[arg-type]
            portfolio_snapshot_id=payload["portfolio_snapshot_id"],  # type: ignore[arg-type]
            original_axis_id=payload["original_axis_id"],  # type: ignore[arg-type]
            original_axis_identity=payload["original_axis_identity"],  # type: ignore[arg-type]
            invalidation_id=payload["invalidation_id"],  # type: ignore[arg-type]
            invalidated_source_contract_id=payload[
                "invalidated_source_contract_id"
            ],  # type: ignore[arg-type]
            replacement_source_contract_id=payload[
                "replacement_source_contract_id"
            ],  # type: ignore[arg-type]
            replacement_source_state_record_id=payload[
                "replacement_source_state_record_id"
            ],  # type: ignore[arg-type]
            replacement_axis_id=payload["replacement_axis_id"],  # type: ignore[arg-type]
            replacement_axis_identity=payload[
                "replacement_axis_identity"
            ],  # type: ignore[arg-type]
        )


__all__ = [
    "AUDIT_MANIFEST_SCHEMA",
    "AUTHORITY_LATCH_SCHEMA",
    "AUTHORITY_RECOVERY_POLICY",
    "AUTHORITY_TRANSITION_EVIDENCE",
    "SOURCE_REPLACEMENT_LINEAGE_SCHEMA",
    "SOURCE_REPLACEMENT_CAPABILITY_SET_SCHEMA",
    "SourceAuthorityAuditManifest",
    "SourceAuthorityInvalidation",
    "SourceAuthorityLatch",
    "SourceAuthorityReason",
    "SourceAuthoritySurface",
    "SourceReplacementLineage",
    "source_replacement_capability_id",
    "source_replacement_capability_set_id",
]
