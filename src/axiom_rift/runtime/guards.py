"""Candidate-bound interfaces without speculative ONNX or MT5 adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, unique
from typing import Iterable

from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.core.identity import canonical_digest


class RuntimeClaimError(RuntimeError):
    """Runtime work or a Release exceeds its bound evidence."""


@unique
class EvidenceDepth(StrEnum):
    DISCOVERY = "discovery"
    CONFIRMATION = "confirmation"
    EXECUTION_PROOF = "execution_proof"
    MATERIALIZATION = "materialization"
    RELEASE = "release"


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBinding:
    candidate_id: str
    executable_id: str
    frozen: bool
    source_bindings: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseEvidence:
    completion_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.completion_record_ids) is not tuple
            or not self.completion_record_ids
            or len(set(self.completion_record_ids)) != len(self.completion_record_ids)
        ):
            raise RuntimeClaimError(
                "Release evidence requires unique runtime Job completion references"
            )
        for reference in self.completion_record_ids:
            if type(reference) is not str or not reference.isascii() or not reference:
                raise RuntimeClaimError("Release completion reference must be ASCII")
        object.__setattr__(
            self, "completion_record_ids", tuple(sorted(self.completion_record_ids))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SealedHoldoutManifest:
    artifact_sha256: str
    size_bytes: int
    data_receipt_id: str
    split_identity: str
    row_identity: str
    starts_at_utc: str
    ends_at_utc: str
    predecessor_holdout_id: str | None = None
    value_exposed: bool = False
    scientific_trial_delta: int = 0
    holdout_reveal_delta: int = 0
    identity: str = field(init=False)

    @staticmethod
    def dataset_identity(artifact_sha256: str) -> str:
        return f"dataset:{artifact_sha256}"

    @staticmethod
    def rows_identity(*, artifact_sha256: str, size_bytes: int) -> str:
        return "rows:" + canonical_digest(
            domain="sealed-holdout-rows",
            payload={
                "artifact_sha256": artifact_sha256,
                "size_bytes": size_bytes,
            },
        )

    @staticmethod
    def split_identity_for(
        *,
        row_identity: str,
        starts_at_utc: str,
        ends_at_utc: str,
        predecessor_holdout_id: str | None,
    ) -> str:
        return "split:" + canonical_digest(
            domain="sealed-holdout-split",
            payload={
                "ends_at_utc": ends_at_utc,
                "predecessor_holdout_id": predecessor_holdout_id,
                "row_identity": row_identity,
                "starts_at_utc": starts_at_utc,
            },
        )

    def __post_init__(self) -> None:
        for name in (
            "artifact_sha256",
            "data_receipt_id",
            "split_identity",
            "row_identity",
            "starts_at_utc",
            "ends_at_utc",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or not value.isascii():
                raise RuntimeClaimError(f"holdout {name} must be non-empty ASCII")
        if len(self.artifact_sha256) != 64:
            raise RuntimeClaimError("holdout artifact identity must be SHA-256")
        for name, prefix in (
            ("data_receipt_id", "dataset:"),
            ("split_identity", "split:"),
            ("row_identity", "rows:"),
        ):
            value = getattr(self, name)
            digest = value.removeprefix(prefix)
            if (
                not value.startswith(prefix)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise RuntimeClaimError(f"holdout {name} must be content-addressed")
        if self.predecessor_holdout_id is not None:
            predecessor = self.predecessor_holdout_id
            digest = predecessor.removeprefix("holdout:")
            if (
                not predecessor.startswith("holdout:")
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise RuntimeClaimError("holdout predecessor identity is invalid")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise RuntimeClaimError("holdout size must be positive")
        expected_rows = self.rows_identity(
            artifact_sha256=self.artifact_sha256,
            size_bytes=self.size_bytes,
        )
        expected_split = self.split_identity_for(
            row_identity=expected_rows,
            starts_at_utc=self.starts_at_utc,
            ends_at_utc=self.ends_at_utc,
            predecessor_holdout_id=self.predecessor_holdout_id,
        )
        if (
            self.data_receipt_id != self.dataset_identity(self.artifact_sha256)
            or self.row_identity != expected_rows
            or self.split_identity != expected_split
        ):
            raise RuntimeClaimError(
                "holdout dataset, rows, and split identities are not artifact-derived"
            )
        if self.value_exposed or self.scientific_trial_delta or self.holdout_reveal_delta:
            raise RuntimeClaimError("a sealed holdout cannot carry exposure deltas")
        identity = canonical_digest(
            domain="sealed-holdout",
            payload={
                "data_receipt_id": self.data_receipt_id,
                "ends_at_utc": self.ends_at_utc,
                "predecessor_holdout_id": self.predecessor_holdout_id,
                "row_identity": self.row_identity,
                "schema": "sealed_holdout.v1",
                "split_identity": self.split_identity,
                "starts_at_utc": self.starts_at_utc,
            },
        )
        object.__setattr__(self, "identity", f"holdout:{identity}")


REQUIRED_PARITY = frozenset(
    {
        "raw_input",
        "python_feature_vs_mql_feature",
        "python_model_vs_onnx_runtime",
        "onnx_runtime_vs_ea_inference",
        "python_decision_vs_ea_decision_and_intent",
        "entry_exit_and_position_lifecycle",
        "native_completed_bar_logic",
        "native_real_tick_economics",
    }
)

REQUIRED_CASES = frozenset(
    {
        "cold_start",
        "warmup",
        "duplicate_bar",
        "restart",
        "source_interruption",
        "stale_or_missing_input",
        "model_load_failure",
        "clock_and_dst",
        "symbol_mapping",
        "feature_order_mismatch",
        "missing_kpi",
    }
)

REQUIRED_RELEASE_ARTIFACT_ROLES = frozenset(
    {
        "frozen_executable_manifest",
        "feature_preprocessing_contract",
        "onnx_model_and_io_contract",
        "ea_source",
        "mql_runtime_modules",
        "compile_report",
        "native_execution_report",
        "parity_report",
        "materialization_report",
        "local_handoff_manifest",
    }
)


class RuntimeClaimGuard:
    @staticmethod
    def require_entry(
        *,
        depth: EvidenceDepth,
        candidate: CandidateBinding | None,
    ) -> None:
        if depth not in {
            EvidenceDepth.EXECUTION_PROOF,
            EvidenceDepth.MATERIALIZATION,
        }:
            raise RuntimeClaimError("evidence depth does not authorize runtime work")
        if candidate is None or not candidate.frozen:
            raise RuntimeClaimError("runtime work requires a frozen candidate")

    @staticmethod
    def require_release(
        *,
        candidate: CandidateBinding | None,
        evidence: ReleaseEvidence,
    ) -> None:
        if candidate is None or not candidate.frozen:
            raise RuntimeClaimError("Release requires a frozen candidate")
        if not evidence.completion_record_ids:
            raise RuntimeClaimError("Release requires runtime Job completion references")

    @staticmethod
    def restricted_confirmation_is_untouched(
        *, observed: bool, informed_redesign: bool
    ) -> bool:
        return not (observed and informed_redesign)


def seal_holdout_fixture(store: EvidenceStore, content: bytes) -> SealedHoldoutManifest:
    artifact = store.finalize(content)
    starts_at = "2099-01-01T00:00:00Z"
    ends_at = "2099-01-02T00:00:00Z"
    rows = SealedHoldoutManifest.rows_identity(
        artifact_sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
    )
    return SealedHoldoutManifest(
        artifact_sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        data_receipt_id=SealedHoldoutManifest.dataset_identity(artifact.sha256),
        split_identity=SealedHoldoutManifest.split_identity_for(
            row_identity=rows,
            starts_at_utc=starts_at,
            ends_at_utc=ends_at,
            predecessor_holdout_id=None,
        ),
        row_identity=rows,
        starts_at_utc=starts_at,
        ends_at_utc=ends_at,
    )
