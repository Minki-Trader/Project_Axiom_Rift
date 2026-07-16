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

from axiom_rift.core.identity import canonical_digest
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


AXIS_REOPEN_AUTHORITY_SCHEMA = "axis_reopen_authority.v2"


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
class AxisReopenEvidence:
    """Exact noncredit authority that makes one historical prune reopenable."""

    replay_resolution_record_ids: tuple[str, ...] = ()
    evidence_scope_overlay_ids: tuple[str, ...] = ()
    historical_cost_completion_ids: tuple[str, ...] = ()
    historical_cost_latch_ids: tuple[str, ...] = ()
    historical_cost_negative_memory_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.replay_resolution_record_ids,
            self.evidence_scope_overlay_ids,
            self.historical_cost_completion_ids,
            self.historical_cost_latch_ids,
            self.historical_cost_negative_memory_ids,
        )
        if any(
            type(items) is not tuple
            or any(type(item) is not str for item in items)
            for items in values
        ):
            raise EffectiveAxisError(
                "axis reopen evidence must use frozen identity tuples"
            )
        resolutions, overlays, completions, latches, memories = (
            tuple(sorted(items)) for items in values
        )
        replay_route = bool(resolutions or overlays)
        cost_route = bool(completions or latches or memories)
        if (
            any(len(items) != len(set(items)) for items in (
                resolutions,
                overlays,
                completions,
                latches,
                memories,
            ))
            or (replay_route and not (resolutions and overlays))
            or (cost_route and not (completions and latches and memories))
            or not (replay_route or cost_route)
        ):
            raise EffectiveAxisError(
                "axis reopen authority requires exact replay/scope or cost evidence"
            )
        for record_id in resolutions:
            _identity(
                "axis reopen replay resolution",
                record_id,
                "historical-replay-satisfaction:",
            )
        for overlay_id in overlays:
            _identity(
                "axis reopen evidence-scope overlay",
                overlay_id,
                "historical-evidence-scope:",
            )
        for completion_id in completions:
            if len(completion_id) != 64 or any(
                char not in "0123456789abcdef" for char in completion_id
            ):
                raise EffectiveAxisError(
                    "axis reopen cost completion must be a SHA-256 digest"
                )
        for latch_id in latches:
            _identity(
                "axis reopen historical cost latch",
                latch_id,
                "historical-cost-semantics-latch:",
            )
        for memory_id in memories:
            _identity(
                "axis reopen historical cost negative memory",
                memory_id,
                "negative-memory:",
            )
        object.__setattr__(self, "replay_resolution_record_ids", resolutions)
        object.__setattr__(self, "evidence_scope_overlay_ids", overlays)
        object.__setattr__(self, "historical_cost_completion_ids", completions)
        object.__setattr__(self, "historical_cost_latch_ids", latches)
        object.__setattr__(
            self,
            "historical_cost_negative_memory_ids",
            memories,
        )

    def to_action_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {}
        if self.replay_resolution_record_ids:
            fields.update(
                {
                    "evidence_scope_overlay_ids": list(
                        self.evidence_scope_overlay_ids
                    ),
                    "replay_resolution_record_ids": list(
                        self.replay_resolution_record_ids
                    ),
                }
            )
        if self.historical_cost_completion_ids:
            fields.update(
                {
                    "historical_cost_completion_ids": list(
                        self.historical_cost_completion_ids
                    ),
                    "historical_cost_latch_ids": list(
                        self.historical_cost_latch_ids
                    ),
                    "historical_cost_negative_memory_ids": list(
                        self.historical_cost_negative_memory_ids
                    ),
                }
            )
        return fields


@dataclass(frozen=True, slots=True, kw_only=True)
class AxisReopenAuthority:
    """One-shot authority to reverse one audit-invalidated historical prune.

    The original snapshot remains immutable.  This record binds the exact
    structural Decision, the exact pruned axis, and either every audit-only
    replay/scope identity or every historical cost completion/latch/negative-
    memory identity that made the old prune uncertain.  Only a later snapshot
    derived from that Decision may consume it.
    """

    mission_id: str
    portfolio_snapshot_id: str
    portfolio_decision_id: str
    axis_id: str
    axis_identity: str
    replay_resolution_record_ids: tuple[str, ...]
    evidence_scope_overlay_ids: tuple[str, ...]
    historical_cost_completion_ids: tuple[str, ...] = ()
    historical_cost_latch_ids: tuple[str, ...] = ()
    historical_cost_negative_memory_ids: tuple[str, ...] = ()
    prior_snapshot_status: str = "pruned"
    authorized_snapshot_status: str = "preserved"

    def __post_init__(self) -> None:
        _ascii("axis reopen Mission id", self.mission_id)
        _identity(
            "axis reopen Portfolio snapshot",
            self.portfolio_snapshot_id,
            "portfolio:",
        )
        _identity(
            "axis reopen Portfolio Decision",
            self.portfolio_decision_id,
            "decision:",
        )
        _ascii("axis reopen axis id", self.axis_id)
        _identity("axis reopen axis identity", self.axis_identity, "axis:")
        if (
            self.prior_snapshot_status != "pruned"
            or self.authorized_snapshot_status != "preserved"
        ):
            raise EffectiveAxisError(
                "axis reopen authority may only preserve an audit-deferred prune"
            )
        evidence = AxisReopenEvidence(
            replay_resolution_record_ids=self.replay_resolution_record_ids,
            evidence_scope_overlay_ids=self.evidence_scope_overlay_ids,
            historical_cost_completion_ids=(
                self.historical_cost_completion_ids
            ),
            historical_cost_latch_ids=self.historical_cost_latch_ids,
            historical_cost_negative_memory_ids=(
                self.historical_cost_negative_memory_ids
            ),
        )
        object.__setattr__(
            self,
            "replay_resolution_record_ids",
            evidence.replay_resolution_record_ids,
        )
        object.__setattr__(
            self,
            "evidence_scope_overlay_ids",
            evidence.evidence_scope_overlay_ids,
        )
        object.__setattr__(
            self,
            "historical_cost_completion_ids",
            evidence.historical_cost_completion_ids,
        )
        object.__setattr__(
            self,
            "historical_cost_latch_ids",
            evidence.historical_cost_latch_ids,
        )
        object.__setattr__(
            self,
            "historical_cost_negative_memory_ids",
            evidence.historical_cost_negative_memory_ids,
        )

    @property
    def identity(self) -> str:
        return "axis-reopen-authority:" + canonical_digest(
            domain="axis-reopen-authority",
            payload=self.to_identity_payload(),
        )

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "authorized_snapshot_status": self.authorized_snapshot_status,
            "axis_id": self.axis_id,
            "axis_identity": self.axis_identity,
            "evidence_scope_overlay_ids": list(self.evidence_scope_overlay_ids),
            "historical_cost_completion_ids": list(
                self.historical_cost_completion_ids
            ),
            "historical_cost_latch_ids": list(
                self.historical_cost_latch_ids
            ),
            "historical_cost_negative_memory_ids": list(
                self.historical_cost_negative_memory_ids
            ),
            "mission_id": self.mission_id,
            "portfolio_decision_id": self.portfolio_decision_id,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "prior_snapshot_status": self.prior_snapshot_status,
            "replay_resolution_record_ids": list(
                self.replay_resolution_record_ids
            ),
            "schema": AXIS_REOPEN_AUTHORITY_SCHEMA,
        }


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
    replay_resolution_ids: tuple[str, ...]

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
        resolutions = tuple(sorted(self.replay_resolution_ids))
        if not resolutions or len(resolutions) != len(set(resolutions)):
            raise EffectiveAxisError(
                "evidence-scope replay resolutions must be unique and non-empty"
            )
        for resolution_id in resolutions:
            _identity(
                "evidence-scope replay resolution id",
                resolution_id,
                "historical-replay-satisfaction:",
            )
        object.__setattr__(self, "replay_obligation_ids", obligations)
        object.__setattr__(self, "replay_resolution_ids", resolutions)

    def to_projection_payload(self) -> dict[str, object]:
        return {
            "axis_id": self.axis_id,
            "axis_identity": self.axis_identity,
            "completion_record_id": self.completion_record_id,
            "executable_id": self.executable_id,
            "governing_mission_id": self.governing_mission_id,
            "overlay_record_id": self.overlay_record_id,
            "replay_obligation_ids": list(self.replay_obligation_ids),
            "replay_resolution_ids": list(self.replay_resolution_ids),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCostAxisBinding:
    """One old completion whose native-cost negative authority is qualified."""

    axis_id: str
    axis_identity: str
    completion_record_id: str
    executable_id: str
    latch_record_id: str
    semantic_class: str
    negative_memory_ids: tuple[str, ...]
    preserved_independent_scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        _ascii("historical cost axis id", self.axis_id)
        _identity("historical cost axis identity", self.axis_identity, "axis:")
        completion = _ascii(
            "historical cost completion", self.completion_record_id
        )
        if len(completion) != 64 or any(
            char not in "0123456789abcdef" for char in completion
        ):
            raise EffectiveAxisError(
                "historical cost completion must be a SHA-256 digest"
            )
        _identity(
            "historical cost Executable", self.executable_id, "executable:"
        )
        _identity(
            "historical cost latch",
            self.latch_record_id,
            "historical-cost-semantics-latch:",
        )
        _ascii("historical cost semantic class", self.semantic_class)
        memories = tuple(sorted(self.negative_memory_ids))
        scopes = tuple(sorted(self.preserved_independent_scopes))
        if (
            len(memories) != len(set(memories))
            or any(
                not value.startswith("negative-memory:") for value in memories
            )
            or len(scopes) != len(set(scopes))
            or any(not value.isascii() or not value for value in scopes)
        ):
            raise EffectiveAxisError(
                "historical cost axis authority inventory is malformed"
            )
        object.__setattr__(self, "negative_memory_ids", memories)
        object.__setattr__(self, "preserved_independent_scopes", scopes)

    @property
    def requires_reopen(self) -> bool:
        return bool(self.negative_memory_ids)

    def to_projection_payload(self) -> dict[str, object]:
        return {
            "axis_id": self.axis_id,
            "axis_identity": self.axis_identity,
            "completion_record_id": self.completion_record_id,
            "executable_id": self.executable_id,
            "latch_record_id": self.latch_record_id,
            "negative_memory_ids": list(self.negative_memory_ids),
            "preserved_independent_scopes": list(
                self.preserved_independent_scopes
            ),
            "semantic_class": self.semantic_class,
        }


def _project_effective_status(
    *,
    snapshot_status: str,
    invalidations: tuple[SourceInvalidationBinding, ...],
    source_replacements: tuple[SourceReplacementBinding, ...],
    replay_bindings: tuple[ReplayAxisBinding, ...],
    evidence_scope_bindings: tuple[EvidenceScopeAxisBinding, ...],
    historical_cost_bindings: tuple[HistoricalCostAxisBinding, ...],
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
    cost_qualified_negative = any(
        item.requires_reopen for item in historical_cost_bindings
    )
    if snapshot_status == "deferred" or (
        snapshot_status == "pruned"
        and (audit_only_completion_scope or cost_qualified_negative)
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
    historical_cost_bindings: tuple[HistoricalCostAxisBinding, ...] = ()

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
        cost_bindings = tuple(
            sorted(
                self.historical_cost_bindings,
                key=lambda item: item.completion_record_id,
            )
        )
        if any(
            not isinstance(item, HistoricalCostAxisBinding)
            for item in cost_bindings
        ) or len({item.completion_record_id for item in cost_bindings}) != len(
            cost_bindings
        ):
            raise EffectiveAxisError(
                "historical cost axis bindings are malformed or ambiguous"
            )
        if any(
            item.axis_id != self.axis_id
            or item.axis_identity != self.axis_identity
            for item in cost_bindings
        ):
            raise EffectiveAxisError(
                "historical cost binding belongs to another axis"
            )
        expected = _project_effective_status(
            snapshot_status=self.snapshot_status,
            invalidations=invalidations,
            source_replacements=source_replacements,
            replay_bindings=replay_bindings,
            evidence_scope_bindings=scope_bindings,
            historical_cost_bindings=cost_bindings,
        )
        if self.effective_status is not expected:
            raise EffectiveAxisError("effective axis status conflicts with its authority")
        object.__setattr__(self, "source_contract_ids", sources)
        object.__setattr__(self, "invalidations", invalidations)
        object.__setattr__(self, "source_replacements", source_replacements)
        object.__setattr__(self, "replay_bindings", replay_bindings)
        object.__setattr__(self, "evidence_scope_bindings", scope_bindings)
        object.__setattr__(self, "historical_cost_bindings", cost_bindings)

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

        if (
            self.effective_status
            is EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN
            and any(
                item.requires_reopen for item in self.historical_cost_bindings
            )
        ):
            return False
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
            "historical_cost_bindings": [
                item.to_projection_payload()
                for item in self.historical_cost_bindings
            ],
            "schema": "effective_portfolio_axis.v4",
            "snapshot_status": self.snapshot_status,
            "source_contract_ids": list(self.source_contract_ids),
            "decision_option_eligible": self.decision_option_eligible,
            "requires_reopen": self.requires_reopen,
            "terminal_eligible": self.terminal_eligible,
        }


def axis_reopen_evidence(
    resolution: EffectiveAxisResolution,
) -> AxisReopenEvidence:
    """Project the exact noncredit evidence behind one deferred old prune."""

    if (
        not isinstance(resolution, EffectiveAxisResolution)
        or resolution.effective_status
        is not EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN
        or resolution.snapshot_status != "pruned"
    ):
        raise EffectiveAxisError(
            "axis reopen authority requires one audit-deferred historical prune"
        )
    audit_bindings = tuple(
        binding
        for binding in resolution.replay_bindings
        if binding.status is ReplayObligationStatus.SATISFIED
        and binding.resolution_scope is ReplayResolutionScope.AUDIT_ONLY
    )
    replay_resolution_ids = tuple(
        sorted(
            {binding.state_record_id for binding in audit_bindings}.union(
                resolution_id
                for binding in resolution.evidence_scope_bindings
                for resolution_id in binding.replay_resolution_ids
            )
        )
    )
    binding_overlay_ids = {
        binding.evidence_scope_overlay_id
        for binding in audit_bindings
        if binding.evidence_scope_overlay_id is not None
    }
    evidence_scope_overlay_ids = tuple(
        sorted(
            binding_overlay_ids.union(
                binding.overlay_record_id
                for binding in resolution.evidence_scope_bindings
            )
        )
    )
    cost_bindings = tuple(
        binding
        for binding in resolution.historical_cost_bindings
        if binding.requires_reopen
    )
    return AxisReopenEvidence(
        replay_resolution_record_ids=replay_resolution_ids,
        evidence_scope_overlay_ids=evidence_scope_overlay_ids,
        historical_cost_completion_ids=tuple(
            binding.completion_record_id for binding in cost_bindings
        ),
        historical_cost_latch_ids=tuple(
            {binding.latch_record_id for binding in cost_bindings}
        ),
        historical_cost_negative_memory_ids=tuple(
            {
                memory_id
                for binding in cost_bindings
                for memory_id in binding.negative_memory_ids
            }
        ),
    )


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
    historical_cost_bindings: tuple[HistoricalCostAxisBinding, ...] = (),
) -> EffectiveAxisResolution:
    """Resolve current selectability without mutating the historical snapshot."""

    status = _project_effective_status(
        snapshot_status=snapshot_status,
        invalidations=invalidations,
        source_replacements=source_replacements,
        replay_bindings=replay_bindings,
        evidence_scope_bindings=evidence_scope_bindings,
        historical_cost_bindings=historical_cost_bindings,
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
        historical_cost_bindings=historical_cost_bindings,
    )


__all__ = [
    "AXIS_REOPEN_AUTHORITY_SCHEMA",
    "AxisReopenAuthority",
    "AxisReopenEvidence",
    "EffectiveAxisError",
    "EffectiveAxisResolution",
    "EffectiveAxisStatus",
    "EvidenceScopeAxisBinding",
    "HistoricalCostAxisBinding",
    "ReplayAxisBinding",
    "SourceInvalidationBinding",
    "SourceReplacementBinding",
    "axis_reopen_evidence",
    "resolve_effective_axis",
]
