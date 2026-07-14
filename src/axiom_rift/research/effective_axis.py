"""Pure effective-status projection for immutable Portfolio axes.

Axis snapshots are historical authority and must not be rewritten when a data
source is later invalidated.  Selection nevertheless has to fail closed.  The
projection below keeps those two concerns separate: the snapshot status stays
unchanged while current source, replay, and evidence-scope authority determines
whether the axis may be selected or used at a Mission terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from axiom_rift.research.replay_obligation import (
    ReplayObligationStatus,
    ReplayResolutionScope,
)


class EffectiveAxisError(ValueError):
    """Raised when current axis-source authority cannot be resolved exactly."""


class EffectiveAxisStatus(str, Enum):
    SELECTABLE = "selectable"
    PRUNED = "pruned"
    DEFERRED_REQUIRES_REOPEN = "deferred_requires_reopen"
    RETIRED_BY_SOURCE_REPLACEMENT = "retired_by_source_replacement"
    BLOCKED_BY_REPLAY_OBLIGATION = "blocked_by_replay_obligation"
    BLOCKED_BY_INVALIDATED_SOURCE = "blocked_by_invalidated_source"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EffectiveAxisError(f"{name} must be non-empty ASCII")
    return value


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    suffix = text.removeprefix(prefix)
    if text == suffix or len(suffix) != 64 or any(
        char not in "0123456789abcdef" for char in suffix
    ):
        raise EffectiveAxisError(f"{name} must use {prefix}<sha256>")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceInvalidationBinding:
    source_contract_id: str
    invalidation_record_id: str

    def __post_init__(self) -> None:
        _identity("source contract id", self.source_contract_id, "source:")
        _identity(
            "source invalidation id",
            self.invalidation_record_id,
            "source-authority-invalidation:",
        )

    def to_projection_payload(self) -> dict[str, str]:
        return {
            "invalidation_record_id": self.invalidation_record_id,
            "source_contract_id": self.source_contract_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceReplacementBinding:
    """One Writer-verified successor branch for an invalidated source axis."""

    record_id: str
    mission_id: str
    original_axis_id: str
    original_axis_identity: str
    invalidation_record_id: str
    invalidated_source_contract_id: str
    replacement_source_contract_id: str
    replacement_source_state_record_id: str
    replacement_axis_id: str
    replacement_axis_identity: str

    def __post_init__(self) -> None:
        _identity(
            "source replacement record id",
            self.record_id,
            "source-replacement-lineage:",
        )
        _ascii("source replacement Mission id", self.mission_id)
        _ascii("source replacement original axis id", self.original_axis_id)
        _identity(
            "source replacement original axis identity",
            self.original_axis_identity,
            "axis:",
        )
        _identity(
            "source replacement invalidation id",
            self.invalidation_record_id,
            "source-authority-invalidation:",
        )
        _identity(
            "source replacement invalidated contract",
            self.invalidated_source_contract_id,
            "source:",
        )
        _identity(
            "source replacement contract",
            self.replacement_source_contract_id,
            "source:",
        )
        replacement_state = _ascii(
            "source replacement state record id",
            self.replacement_source_state_record_id,
        )
        if len(replacement_state) != 64 or any(
            character not in "0123456789abcdef"
            for character in replacement_state
        ):
            raise EffectiveAxisError(
                "source replacement state record id must be a SHA-256 digest"
            )
        _ascii("source replacement axis id", self.replacement_axis_id)
        _identity(
            "source replacement axis identity",
            self.replacement_axis_identity,
            "axis:",
        )
        if (
            self.invalidated_source_contract_id
            == self.replacement_source_contract_id
            or self.original_axis_id == self.replacement_axis_id
            or self.original_axis_identity == self.replacement_axis_identity
        ):
            raise EffectiveAxisError(
                "source replacement must bind distinct source and axis identities"
            )

    def to_projection_payload(self) -> dict[str, str]:
        return {
            "invalidation_record_id": self.invalidation_record_id,
            "invalidated_source_contract_id": self.invalidated_source_contract_id,
            "mission_id": self.mission_id,
            "original_axis_id": self.original_axis_id,
            "original_axis_identity": self.original_axis_identity,
            "record_id": self.record_id,
            "replacement_axis_id": self.replacement_axis_id,
            "replacement_axis_identity": self.replacement_axis_identity,
            "replacement_source_contract_id": self.replacement_source_contract_id,
            "replacement_source_state_record_id": (
                self.replacement_source_state_record_id
            ),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayAxisBinding:
    """Current replay state bound to the immutable original Executable axis."""

    axis_id: str
    axis_identity: str
    governing_mission_id: str
    obligation_id: str
    original_executable_id: str
    original_study_id: str
    state_record_id: str
    status: ReplayObligationStatus
    resolution_scope: ReplayResolutionScope | None = None
    evidence_scope_overlay_id: str | None = None

    def __post_init__(self) -> None:
        _ascii("replay axis id", self.axis_id)
        _identity("replay axis identity", self.axis_identity, "axis:")
        _ascii("replay governing Mission id", self.governing_mission_id)
        _identity(
            "replay obligation id",
            self.obligation_id,
            "historical-replay-obligation:",
        )
        _identity(
            "replay original Executable id",
            self.original_executable_id,
            "executable:",
        )
        _ascii("replay original Study id", self.original_study_id)
        _ascii("replay state record id", self.state_record_id)
        if not isinstance(self.status, ReplayObligationStatus):
            raise EffectiveAxisError("replay obligation status is not typed")
        if self.resolution_scope is not None and not isinstance(
            self.resolution_scope, ReplayResolutionScope
        ):
            raise EffectiveAxisError("replay resolution scope is not typed")
        unresolved = self.status in {
            ReplayObligationStatus.PENDING,
            ReplayObligationStatus.IN_PROGRESS,
            ReplayObligationStatus.DEFERRED,
        }
        if unresolved and (
            self.resolution_scope is not None
            or self.evidence_scope_overlay_id is not None
        ):
            raise EffectiveAxisError(
                "unresolved replay cannot carry satisfaction scope"
            )
        if self.status is ReplayObligationStatus.SATISFIED:
            if self.resolution_scope is None:
                raise EffectiveAxisError(
                    "satisfied replay requires a typed resolution scope"
                )
            if self.resolution_scope is ReplayResolutionScope.AUDIT_ONLY:
                _identity(
                    "audit-only evidence scope overlay id",
                    self.evidence_scope_overlay_id,
                    "historical-evidence-scope:",
                )
            elif self.evidence_scope_overlay_id is not None:
                raise EffectiveAxisError(
                    "scientific replay cannot retain an audit-only overlay"
                )

    @property
    def blocks_selection(self) -> bool:
        return self.status is not ReplayObligationStatus.SATISFIED

    @property
    def blocks_terminal(self) -> bool:
        return self.status in {
            ReplayObligationStatus.PENDING,
            ReplayObligationStatus.IN_PROGRESS,
            ReplayObligationStatus.DEFERRED,
        }

    def to_projection_payload(self) -> dict[str, object]:
        return {
            "axis_id": self.axis_id,
            "axis_identity": self.axis_identity,
            "evidence_scope_overlay_id": self.evidence_scope_overlay_id,
            "governing_mission_id": self.governing_mission_id,
            "obligation_id": self.obligation_id,
            "original_executable_id": self.original_executable_id,
            "original_study_id": self.original_study_id,
            "resolution_scope": (
                None
                if self.resolution_scope is None
                else self.resolution_scope.value
            ),
            "state_record_id": self.state_record_id,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceScopeAxisBinding:
    """Audit-only completion overlay bound to its exact Executable axis."""

    axis_id: str
    axis_identity: str
    completion_record_id: str
    executable_id: str
    governing_mission_id: str
    overlay_record_id: str
    replay_obligation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _ascii("evidence-scope axis id", self.axis_id)
        _identity("evidence-scope axis identity", self.axis_identity, "axis:")
        _ascii("evidence-scope governing Mission id", self.governing_mission_id)
        completion = _ascii(
            "evidence-scope completion record id", self.completion_record_id
        )
        if len(completion) != 64 or any(
            char not in "0123456789abcdef" for char in completion
        ):
            raise EffectiveAxisError(
                "evidence-scope completion record id must be a SHA-256 digest"
            )
        _identity("evidence-scope Executable id", self.executable_id, "executable:")
        _identity(
            "evidence-scope overlay id",
            self.overlay_record_id,
            "historical-evidence-scope:",
        )
        obligations = tuple(sorted(self.replay_obligation_ids))
        if not obligations or len(obligations) != len(set(obligations)):
            raise EffectiveAxisError(
                "evidence-scope replay obligations must be unique and non-empty"
            )
        for obligation_id in obligations:
            _identity(
                "evidence-scope replay obligation id",
                obligation_id,
                "historical-replay-obligation:",
            )
        object.__setattr__(self, "replay_obligation_ids", obligations)

    def to_projection_payload(self) -> dict[str, object]:
        return {
            "axis_id": self.axis_id,
            "axis_identity": self.axis_identity,
            "completion_record_id": self.completion_record_id,
            "executable_id": self.executable_id,
            "governing_mission_id": self.governing_mission_id,
            "overlay_record_id": self.overlay_record_id,
            "replay_obligation_ids": list(self.replay_obligation_ids),
        }


def _project_effective_status(
    *,
    snapshot_status: str,
    invalidations: tuple[SourceInvalidationBinding, ...],
    source_replacements: tuple[SourceReplacementBinding, ...],
    replay_bindings: tuple[ReplayAxisBinding, ...],
    evidence_scope_bindings: tuple[EvidenceScopeAxisBinding, ...],
) -> EffectiveAxisStatus:
    """Project axis authority without promoting completion scope to axis scope."""

    if invalidations:
        invalidated_sources = {
            item.source_contract_id for item in invalidations
        }
        replaced_sources = {
            item.invalidated_source_contract_id
            for item in source_replacements
        }
        if replaced_sources == invalidated_sources:
            return EffectiveAxisStatus.RETIRED_BY_SOURCE_REPLACEMENT
        return EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE
    if source_replacements:
        raise EffectiveAxisError(
            "source replacement binding lacks an invalidated source"
        )
    if any(item.blocks_terminal for item in replay_bindings):
        return EffectiveAxisStatus.BLOCKED_BY_REPLAY_OBLIGATION
    audit_only_completion_scope = bool(evidence_scope_bindings) or any(
        item.status is ReplayObligationStatus.SATISFIED
        and item.resolution_scope is ReplayResolutionScope.AUDIT_ONLY
        for item in replay_bindings
    )
    if snapshot_status == "deferred" or (
        snapshot_status == "pruned" and audit_only_completion_scope
    ):
        # Current authority cannot prove that a historical prune was independent
        # of the now zero-credit completion.  Reopen it explicitly rather than
        # silently preserving or reversing the immutable snapshot decision.
        return EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN
    if snapshot_status == "pruned":
        return EffectiveAxisStatus.PRUNED
    return EffectiveAxisStatus.SELECTABLE


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectiveAxisResolution:
    axis_id: str
    axis_identity: str
    snapshot_status: str
    source_contract_ids: tuple[str, ...]
    invalidations: tuple[SourceInvalidationBinding, ...]
    source_replacements: tuple[SourceReplacementBinding, ...]
    replay_bindings: tuple[ReplayAxisBinding, ...]
    evidence_scope_bindings: tuple[EvidenceScopeAxisBinding, ...]
    effective_status: EffectiveAxisStatus

    def __post_init__(self) -> None:
        _ascii("axis id", self.axis_id)
        _identity("axis identity", self.axis_identity, "axis:")
        if self.snapshot_status not in {"open", "preserved", "deferred", "pruned"}:
            raise EffectiveAxisError("Portfolio snapshot axis status is invalid")
        sources = tuple(sorted(self.source_contract_ids))
        if len(sources) != len(set(sources)):
            raise EffectiveAxisError("axis source contracts must be unique")
        for source_id in sources:
            _identity("axis source contract", source_id, "source:")
        invalidations = tuple(
            sorted(self.invalidations, key=lambda item: item.source_contract_id)
        )
        if any(not isinstance(item, SourceInvalidationBinding) for item in invalidations):
            raise EffectiveAxisError("axis invalidation bindings are not typed")
        if len({item.source_contract_id for item in invalidations}) != len(
            invalidations
        ):
            raise EffectiveAxisError("axis invalidation sources must be unique")
        if any(item.source_contract_id not in sources for item in invalidations):
            raise EffectiveAxisError("axis invalidation is unrelated to its source lineage")
        source_replacements = tuple(
            sorted(
                self.source_replacements,
                key=lambda item: item.invalidated_source_contract_id,
            )
        )
        if any(
            not isinstance(item, SourceReplacementBinding)
            for item in source_replacements
        ):
            raise EffectiveAxisError("axis source replacement bindings are not typed")
        if len(
            {item.invalidated_source_contract_id for item in source_replacements}
        ) != len(source_replacements):
            raise EffectiveAxisError(
                "axis source replacement contracts must be unique"
            )
        invalidations_by_source = {
            item.source_contract_id: item.invalidation_record_id
            for item in invalidations
        }
        if any(
            item.original_axis_id != self.axis_id
            or item.original_axis_identity != self.axis_identity
            or invalidations_by_source.get(item.invalidated_source_contract_id)
            != item.invalidation_record_id
            for item in source_replacements
        ):
            raise EffectiveAxisError(
                "source replacement binding belongs to another axis or invalidation"
            )
        replay_bindings = tuple(
            sorted(self.replay_bindings, key=lambda item: item.obligation_id)
        )
        if any(not isinstance(item, ReplayAxisBinding) for item in replay_bindings):
            raise EffectiveAxisError("axis replay bindings are not typed")
        if len({item.obligation_id for item in replay_bindings}) != len(
            replay_bindings
        ):
            raise EffectiveAxisError("axis replay obligations must be unique")
        if any(
            item.axis_id != self.axis_id
            or item.axis_identity != self.axis_identity
            for item in replay_bindings
        ):
            raise EffectiveAxisError("replay binding belongs to another axis")
        scope_bindings = tuple(
            sorted(
                self.evidence_scope_bindings,
                key=lambda item: item.overlay_record_id,
            )
        )
        if any(
            not isinstance(item, EvidenceScopeAxisBinding)
            for item in scope_bindings
        ):
            raise EffectiveAxisError("axis evidence-scope bindings are not typed")
        if len({item.overlay_record_id for item in scope_bindings}) != len(
            scope_bindings
        ):
            raise EffectiveAxisError("axis evidence-scope overlays must be unique")
        if any(
            item.axis_id != self.axis_id
            or item.axis_identity != self.axis_identity
            for item in scope_bindings
        ):
            raise EffectiveAxisError("evidence-scope binding belongs to another axis")
        expected = _project_effective_status(
            snapshot_status=self.snapshot_status,
            invalidations=invalidations,
            source_replacements=source_replacements,
            replay_bindings=replay_bindings,
            evidence_scope_bindings=scope_bindings,
        )
        if self.effective_status is not expected:
            raise EffectiveAxisError("effective axis status conflicts with its authority")
        object.__setattr__(self, "source_contract_ids", sources)
        object.__setattr__(self, "invalidations", invalidations)
        object.__setattr__(self, "source_replacements", source_replacements)
        object.__setattr__(self, "replay_bindings", replay_bindings)
        object.__setattr__(self, "evidence_scope_bindings", scope_bindings)

    @property
    def status(self) -> EffectiveAxisStatus:
        """Compatibility alias used by read-only scheduler projections."""

        return self.effective_status

    @property
    def selectable(self) -> bool:
        return self.effective_status is EffectiveAxisStatus.SELECTABLE

    @property
    def decision_option_eligible(self) -> bool:
        """Whether the axis may remain visible in a forest Decision option set."""

        return self.effective_status in {
            EffectiveAxisStatus.SELECTABLE,
            EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN,
        }

    @property
    def requires_reopen(self) -> bool:
        return (
            self.effective_status
            is EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN
        )

    @property
    def terminal_eligible(self) -> bool:
        """Whether current authority permits later terminal interpretation.

        This does not itself prove exhaustion.  It only rejects axes whose
        current source, replay, or scope authority is unresolved.
        """

        return self.effective_status in {
            EffectiveAxisStatus.SELECTABLE,
            EffectiveAxisStatus.PRUNED,
            EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN,
            EffectiveAxisStatus.RETIRED_BY_SOURCE_REPLACEMENT,
        }

    @property
    def blocking_replay_obligation_ids(self) -> tuple[str, ...]:
        return tuple(
            item.obligation_id
            for item in self.replay_bindings
            if item.blocks_selection
        )

    def to_projection_payload(self) -> dict[str, object]:
        return {
            "axis_id": self.axis_id,
            "axis_identity": self.axis_identity,
            "effective_status": self.effective_status.value,
            "invalidations": [
                item.to_projection_payload() for item in self.invalidations
            ],
            "source_replacements": [
                item.to_projection_payload() for item in self.source_replacements
            ],
            "replay_bindings": [
                item.to_projection_payload() for item in self.replay_bindings
            ],
            "evidence_scope_bindings": [
                item.to_projection_payload()
                for item in self.evidence_scope_bindings
            ],
            "schema": "effective_portfolio_axis.v3",
            "snapshot_status": self.snapshot_status,
            "source_contract_ids": list(self.source_contract_ids),
            "decision_option_eligible": self.decision_option_eligible,
            "requires_reopen": self.requires_reopen,
            "terminal_eligible": self.terminal_eligible,
        }


def resolve_effective_axis(
    *,
    axis_id: str,
    axis_identity: str,
    snapshot_status: str,
    source_contract_ids: tuple[str, ...],
    invalidations: tuple[SourceInvalidationBinding, ...],
    source_replacements: tuple[SourceReplacementBinding, ...] = (),
    replay_bindings: tuple[ReplayAxisBinding, ...] = (),
    evidence_scope_bindings: tuple[EvidenceScopeAxisBinding, ...] = (),
) -> EffectiveAxisResolution:
    """Resolve current selectability without mutating the historical snapshot."""

    status = _project_effective_status(
        snapshot_status=snapshot_status,
        invalidations=invalidations,
        source_replacements=source_replacements,
        replay_bindings=replay_bindings,
        evidence_scope_bindings=evidence_scope_bindings,
    )
    return EffectiveAxisResolution(
        axis_id=axis_id,
        axis_identity=axis_identity,
        snapshot_status=snapshot_status,
        source_contract_ids=source_contract_ids,
        invalidations=invalidations,
        source_replacements=source_replacements,
        replay_bindings=replay_bindings,
        evidence_scope_bindings=evidence_scope_bindings,
        effective_status=status,
    )


__all__ = [
    "EffectiveAxisError",
    "EffectiveAxisResolution",
    "EffectiveAxisStatus",
    "EvidenceScopeAxisBinding",
    "ReplayAxisBinding",
    "SourceInvalidationBinding",
    "SourceReplacementBinding",
    "resolve_effective_axis",
]
