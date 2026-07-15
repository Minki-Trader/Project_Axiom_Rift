"""Typed research-direction records for Mission and Study boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from axiom_rift.core.canonical import CanonicalValue
from axiom_rift.core.identity import canonical_digest


class ResearchGovernanceError(ValueError):
    """Raised when research direction is incomplete or ambiguous."""


class ResearchLayer(str, Enum):
    DATA_SOURCE = "data_source"
    FEATURE = "feature"
    LABEL = "label"
    MODEL = "model"
    OBJECTIVE = "objective"
    CALIBRATION = "calibration"
    SELECTOR = "selector"
    TRADE = "trade"
    LIFECYCLE = "lifecycle"
    RISK = "risk"
    REGIME = "regime"
    EXECUTION = "execution"
    SYNTHESIS = "synthesis"
    PORTFOLIO = "portfolio"


class EvidenceState(str, Enum):
    ABSENT_INFORMATION = "absent_information"
    TARGET_MISMATCH = "target_mismatch"
    MODEL_CAPACITY = "model_capacity"
    CALIBRATION_SELECTION = "calibration_selection"
    ENTRY_POLICY = "entry_policy"
    LIFECYCLE_RISK = "lifecycle_risk"
    EXECUTION_COST = "execution_cost"
    STABILITY_CONCENTRATION = "stability_concentration"
    SUPPORTED_REQUIRES_CONFIRMATION = "supported_requires_confirmation"
    NOT_IDENTIFIABLE = "not_identifiable"
    ENGINEERING_GAP = "engineering_gap"


class DiagnosisConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ArchitectureReviewConclusion(str, Enum):
    BOUNDED_SAME_ARCHITECTURE = "bounded_same_architecture"
    CHANGE_RESEARCH_LAYER = "change_research_layer"
    ROTATE_ARCHITECTURE = "rotate_architecture"


class ArchitectureContinuationMode(str, Enum):
    EXISTING_AXIS = "existing_axis"
    NEW_MECHANISM = "new_mechanism"


REQUIRED_INTAKE_SURFACES = frozenset(
    {
        "executable_components",
        "mission_terminals",
        "negative_memory",
        "portfolio_decisions",
        "study_kpi",
        "study_questions",
        "validator_evidence",
    }
)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ResearchGovernanceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ResearchGovernanceError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _ascii_values(
    name: str,
    values: tuple[str, ...],
    *,
    minimum: int = 1,
) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) < minimum:
        raise ResearchGovernanceError(f"{name} must be a frozen non-empty tuple")
    normalized = tuple(sorted(_ascii(name, value) for value in values))
    if len(set(normalized)) != len(normalized):
        raise ResearchGovernanceError(f"{name} must be unique")
    return normalized


def _layer_values(
    name: str,
    values: tuple[ResearchLayer, ...],
) -> tuple[ResearchLayer, ...]:
    if type(values) is not tuple or not values:
        raise ResearchGovernanceError(f"{name} must be a frozen non-empty tuple")
    if any(not isinstance(value, ResearchLayer) for value in values):
        raise ResearchGovernanceError(f"{name} must contain ResearchLayer values")
    normalized = tuple(sorted(values, key=lambda value: value.value))
    if len(set(normalized)) != len(normalized):
        raise ResearchGovernanceError(f"{name} must be unique")
    return normalized


def require_architecture_family(value: object) -> str:
    text = _ascii("system_architecture_family", value)
    if not text.startswith("architecture-family:"):
        raise ResearchGovernanceError(
            "system_architecture_family must use the architecture-family namespace"
        )
    return text


def _prefixed_digest(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise ResearchGovernanceError(f"{name} must use the {prefix} namespace")
    _digest(name, text.removeprefix(prefix))
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionResearchIntake:
    mission_id: str
    history_head_sequence: int
    history_head_event_id: str
    reviewed_surfaces: tuple[str, ...]
    mission_thesis: str
    architecture_findings: tuple[str, ...]
    bottleneck_hypotheses: tuple[str, ...]
    underexplored_layers: tuple[ResearchLayer, ...]
    legacy_limitations: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("mission_id", self.mission_id)
        if type(self.history_head_sequence) is not int or self.history_head_sequence < 1:
            raise ResearchGovernanceError("history_head_sequence must be positive")
        _digest("history_head_event_id", self.history_head_event_id)
        reviewed = _ascii_values("reviewed_surfaces", self.reviewed_surfaces)
        if set(reviewed) != REQUIRED_INTAKE_SURFACES:
            raise ResearchGovernanceError(
                "research intake must cover every required history surface"
            )
        object.__setattr__(self, "reviewed_surfaces", reviewed)
        object.__setattr__(
            self,
            "architecture_findings",
            _ascii_values("architecture_findings", self.architecture_findings),
        )
        object.__setattr__(
            self,
            "bottleneck_hypotheses",
            _ascii_values(
                "bottleneck_hypotheses",
                self.bottleneck_hypotheses,
                minimum=2,
            ),
        )
        object.__setattr__(
            self,
            "underexplored_layers",
            _layer_values("underexplored_layers", self.underexplored_layers),
        )
        _ascii("mission_thesis", self.mission_thesis)
        _ascii("legacy_limitations", self.legacy_limitations)
        object.__setattr__(
            self,
            "identity",
            "research-intake:"
            + canonical_digest(
                domain="mission-research-intake",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "architecture_findings": list(self.architecture_findings),
            "bottleneck_hypotheses": list(self.bottleneck_hypotheses),
            "history_head_event_id": self.history_head_event_id,
            "history_head_sequence": self.history_head_sequence,
            "legacy_limitations": self.legacy_limitations,
            "mission_id": self.mission_id,
            "mission_thesis": self.mission_thesis,
            "reviewed_surfaces": list(self.reviewed_surfaces),
            "schema": "mission_research_intake.v1",
            "underexplored_layers": [
                layer.value for layer in self.underexplored_layers
            ],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class StudyDiagnosis:
    study_id: str
    study_close_record_id: str
    evidence_state: EvidenceState
    confidence: DiagnosisConfidence
    rationale: str
    counterfactual: str
    reopen_condition: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("study_id", self.study_id)
        _digest("study_close_record_id", self.study_close_record_id)
        if not isinstance(self.evidence_state, EvidenceState):
            raise ResearchGovernanceError("evidence_state is not typed")
        if not isinstance(self.confidence, DiagnosisConfidence):
            raise ResearchGovernanceError("diagnosis confidence is not typed")
        for name in ("rationale", "counterfactual", "reopen_condition"):
            _ascii(name, getattr(self, name))
        object.__setattr__(
            self,
            "identity",
            "diagnosis:"
            + canonical_digest(
                domain="study-diagnosis",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "confidence": self.confidence.value,
            "counterfactual": self.counterfactual,
            "evidence_state": self.evidence_state.value,
            "rationale": self.rationale,
            "reopen_condition": self.reopen_condition,
            "schema": "study_diagnosis.v1",
            "study_close_record_id": self.study_close_record_id,
            "study_id": self.study_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchitectureContinuationDirection:
    """One expert-selected, review-bound same-architecture continuation."""

    mode: ArchitectureContinuationMode
    reviewed_architecture_family: str
    trigger_record_id: str
    covered_diagnosis_ids: tuple[str, ...]
    target_axis_id: str | None = None
    target_axis_identity: str | None = None
    required_research_layer: ResearchLayer | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ArchitectureContinuationMode):
            raise ResearchGovernanceError("architecture continuation mode is not typed")
        require_architecture_family(self.reviewed_architecture_family)
        _digest("architecture continuation trigger", self.trigger_record_id)
        diagnoses = _ascii_values(
            "covered_diagnosis_ids",
            self.covered_diagnosis_ids,
        )
        for diagnosis_id in diagnoses:
            _prefixed_digest(
                "covered diagnosis identity",
                diagnosis_id,
                "diagnosis:",
            )
        object.__setattr__(self, "covered_diagnosis_ids", diagnoses)
        if self.mode is ArchitectureContinuationMode.EXISTING_AXIS:
            _ascii("target_axis_id", self.target_axis_id)
            _prefixed_digest(
                "target_axis_identity",
                self.target_axis_identity,
                "axis:",
            )
            if self.required_research_layer is not None:
                raise ResearchGovernanceError(
                    "existing-axis continuation cannot select a new research layer"
                )
        else:
            if self.target_axis_id is not None or self.target_axis_identity is not None:
                raise ResearchGovernanceError(
                    "new-mechanism continuation cannot preselect an existing axis"
                )
            if not isinstance(self.required_research_layer, ResearchLayer):
                raise ResearchGovernanceError(
                    "new-mechanism continuation requires one typed research layer"
                )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        payload: dict[str, CanonicalValue] = {
            "covered_diagnosis_ids": list(self.covered_diagnosis_ids),
            "mode": self.mode.value,
            "reviewed_architecture_family": self.reviewed_architecture_family,
            "schema": "architecture_continuation_direction.v1",
            "trigger_record_id": self.trigger_record_id,
        }
        if self.mode is ArchitectureContinuationMode.EXISTING_AXIS:
            assert self.target_axis_id is not None
            assert self.target_axis_identity is not None
            payload.update(
                {
                    "target_axis_id": self.target_axis_id,
                    "target_axis_identity": self.target_axis_identity,
                }
            )
        else:
            assert self.required_research_layer is not None
            payload["required_research_layer"] = self.required_research_layer.value
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchitectureReview:
    mission_id: str
    trigger_record_id: str
    system_architecture_family: str
    conclusion: ArchitectureReviewConclusion
    rationale: str
    stop_or_reopen_condition: str
    continuation_direction: ArchitectureContinuationDirection | None = None
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("mission_id", self.mission_id)
        _digest("trigger_record_id", self.trigger_record_id)
        require_architecture_family(self.system_architecture_family)
        if not isinstance(self.conclusion, ArchitectureReviewConclusion):
            raise ResearchGovernanceError("architecture review conclusion is not typed")
        if self.conclusion is ArchitectureReviewConclusion.BOUNDED_SAME_ARCHITECTURE:
            if not isinstance(
                self.continuation_direction,
                ArchitectureContinuationDirection,
            ):
                raise ResearchGovernanceError(
                    "bounded same-architecture review requires a typed direction"
                )
            if (
                self.continuation_direction.reviewed_architecture_family
                != self.system_architecture_family
                or self.continuation_direction.trigger_record_id
                != self.trigger_record_id
            ):
                raise ResearchGovernanceError(
                    "architecture continuation differs from its parent review"
                )
        elif self.continuation_direction is not None:
            raise ResearchGovernanceError(
                "legacy architecture conclusions cannot carry a continuation direction"
            )
        _ascii("rationale", self.rationale)
        _ascii("stop_or_reopen_condition", self.stop_or_reopen_condition)
        object.__setattr__(
            self,
            "identity",
            "architecture-review:"
            + canonical_digest(
                domain="architecture-review",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        payload: dict[str, CanonicalValue] = {
            "conclusion": self.conclusion.value,
            "mission_id": self.mission_id,
            "rationale": self.rationale,
            "schema": "architecture_review.v1",
            "stop_or_reopen_condition": self.stop_or_reopen_condition,
            "system_architecture_family": self.system_architecture_family,
            "trigger_record_id": self.trigger_record_id,
        }
        if self.continuation_direction is not None:
            payload["continuation_direction"] = (
                self.continuation_direction.to_identity_payload()
            )
            payload["schema"] = "architecture_review.v2"
        return payload


def diagnosis_branch(
    evidence_state: EvidenceState,
    *,
    primary_layer: ResearchLayer,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return writer-enforced local actions and research-layer branches."""

    actions: dict[EvidenceState, tuple[str, ...]] = {
        EvidenceState.ABSENT_INFORMATION: ("new_mechanism", "prune", "rotate"),
        EvidenceState.TARGET_MISMATCH: ("contrast", "new_mechanism", "prune", "rotate"),
        EvidenceState.MODEL_CAPACITY: ("contrast", "new_mechanism", "prune", "rotate"),
        EvidenceState.CALIBRATION_SELECTION: ("contrast", "new_mechanism", "prune", "rotate"),
        EvidenceState.ENTRY_POLICY: ("contrast", "new_mechanism", "prune", "rotate"),
        EvidenceState.LIFECYCLE_RISK: ("contrast", "new_mechanism", "prune", "rotate"),
        EvidenceState.EXECUTION_COST: ("contrast", "new_mechanism", "prune", "rotate"),
        EvidenceState.STABILITY_CONCENTRATION: (
            "complementary_sleeve",
            "contrast",
            "new_mechanism",
            "prune",
            "recombine",
            "rotate",
            "synthesize",
        ),
        EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION: (
            "contrast",
            "deepen",
            "preserve",
            "recombine",
            "synthesize",
        ),
        EvidenceState.NOT_IDENTIFIABLE: (
            "contrast",
            "new_mechanism",
            "prune",
            "rotate",
        ),
        EvidenceState.ENGINEERING_GAP: ("preserve",),
    }
    layers: dict[EvidenceState, tuple[ResearchLayer, ...]] = {
        EvidenceState.ABSENT_INFORMATION: (
            ResearchLayer.DATA_SOURCE,
            ResearchLayer.FEATURE,
        ),
        EvidenceState.TARGET_MISMATCH: (
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.OBJECTIVE,
        ),
        EvidenceState.MODEL_CAPACITY: (
            ResearchLayer.MODEL,
            ResearchLayer.OBJECTIVE,
        ),
        EvidenceState.CALIBRATION_SELECTION: (
            ResearchLayer.CALIBRATION,
            ResearchLayer.SELECTOR,
        ),
        EvidenceState.ENTRY_POLICY: (
            ResearchLayer.SELECTOR,
            ResearchLayer.TRADE,
        ),
        EvidenceState.LIFECYCLE_RISK: (
            ResearchLayer.LIFECYCLE,
            ResearchLayer.RISK,
        ),
        EvidenceState.EXECUTION_COST: (
            ResearchLayer.EXECUTION,
            ResearchLayer.TRADE,
        ),
        EvidenceState.STABILITY_CONCENTRATION: (
            ResearchLayer.PORTFOLIO,
            ResearchLayer.REGIME,
            ResearchLayer.RISK,
            ResearchLayer.SYNTHESIS,
        ),
        EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION: (primary_layer,),
        EvidenceState.NOT_IDENTIFIABLE: (
            ResearchLayer.DATA_SOURCE,
            ResearchLayer.EXECUTION,
            ResearchLayer.LABEL,
        ),
        EvidenceState.ENGINEERING_GAP: (primary_layer,),
    }
    return tuple(sorted(actions[evidence_state])), tuple(
        sorted(layer.value for layer in layers[evidence_state])
    )


__all__ = [
    "ArchitectureContinuationDirection",
    "ArchitectureContinuationMode",
    "ArchitectureReview",
    "ArchitectureReviewConclusion",
    "DiagnosisConfidence",
    "EvidenceState",
    "MissionResearchIntake",
    "REQUIRED_INTAKE_SURFACES",
    "ResearchGovernanceError",
    "ResearchLayer",
    "StudyDiagnosis",
    "diagnosis_branch",
    "require_architecture_family",
]
