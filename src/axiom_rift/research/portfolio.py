"""Frozen adaptive Batches and forest-preserving Portfolio decisions."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import Enum

from axiom_rift.core.canonical import CanonicalValue, canonical_bytes, parse_canonical
from axiom_rift.core.identity import ExecutableSpec, canonical_digest
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ArchitectureRole,
    component_domain,
)
from axiom_rift.research.governance import (
    ResearchGovernanceError,
    ResearchLayer,
    require_architecture_family,
)


class BatchSpecError(ValueError):
    """Raised when a Batch is not bounded and fully frozen."""


class ConcurrentFamilyEvaluationMode(str, Enum):
    """How one exact preregistered family reaches its evidence engine."""

    CONCURRENT = "concurrent"
    VECTORIZED = "vectorized"


@dataclass(frozen=True, slots=True, kw_only=True)
class ConcurrentFamilyManifest:
    """Exact Executable membership for one concurrent selection family."""

    evaluation_mode: ConcurrentFamilyEvaluationMode
    executable_ids: tuple[str, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation_mode, ConcurrentFamilyEvaluationMode):
            raise BatchSpecError("concurrent family evaluation mode must be typed")
        if type(self.executable_ids) is not tuple or len(self.executable_ids) < 2:
            raise BatchSpecError(
                "concurrent family requires at least two exact Executable identities"
            )
        for executable_id in self.executable_ids:
            if (
                type(executable_id) is not str
                or not executable_id.startswith("executable:")
                or len(executable_id) != 75
                or any(
                    character not in "0123456789abcdef"
                    for character in executable_id.removeprefix("executable:")
                )
            ):
                raise BatchSpecError(
                    "concurrent family member must be an exact Executable identity"
                )
        if len(set(self.executable_ids)) != len(self.executable_ids):
            raise BatchSpecError("concurrent family Executable identities must be unique")
        digest = canonical_digest(
            domain="concurrent-family-manifest",
            payload=self.to_identity_payload(),
        )
        object.__setattr__(self, "identity", f"concurrent-family:{digest}")

    @property
    def family_size(self) -> int:
        return len(self.executable_ids)

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "evaluation_mode": self.evaluation_mode.value,
            "executable_ids": list(self.executable_ids),
            "family_size": self.family_size,
            "schema": "concurrent_family_manifest.v1",
        }


class PortfolioDecisionError(ValueError):
    """Raised when a Portfolio decision violates allocation boundaries."""


class DecisionLens(str, Enum):
    """Professional lenses that can be material to one allocation decision."""

    CAUSALITY = "causality"
    STATISTICS = "statistics"
    DATA = "data"
    EXECUTION = "execution"
    ECONOMICS = "economics"
    RISK = "risk"
    ARCHITECTURE = "architecture"


class DecisionLensPosition(str, Enum):
    """A non-numeric lens position on the chosen allocation."""

    SUPPORT = "support"
    CHALLENGE = "challenge"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionBasisRecord:
    """One exact durable record used by a material judgment lens."""

    kind: str
    record_id: str

    def __post_init__(self) -> None:
        _ascii("decision basis kind", self.kind)
        _ascii("decision basis record_id", self.record_id)

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.kind, self.record_id

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {"kind": self.kind, "record_id": self.record_id}


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionLensAssessment:
    """Compact evidence-bound finding, not a role-specific report."""

    lens: DecisionLens
    position: DecisionLensPosition
    option_ids: tuple[str, ...]
    basis_records: tuple[DecisionBasisRecord, ...]
    finding: str

    def __post_init__(self) -> None:
        if not isinstance(self.lens, DecisionLens):
            raise PortfolioDecisionError("decision lens must be typed")
        if not isinstance(self.position, DecisionLensPosition):
            raise PortfolioDecisionError("decision lens position must be typed")
        if type(self.option_ids) is not tuple or not self.option_ids:
            raise PortfolioDecisionError("decision lens must cover an option")
        for option_id in self.option_ids:
            _ascii("decision lens option_id", option_id)
        normalized_options = tuple(sorted(set(self.option_ids)))
        if self.option_ids != normalized_options:
            raise PortfolioDecisionError(
                "decision lens option_ids must be sorted and unique"
            )
        if type(self.basis_records) is not tuple or not self.basis_records:
            raise PortfolioDecisionError(
                "decision lens must cite durable evidence"
            )
        if any(
            not isinstance(record, DecisionBasisRecord)
            for record in self.basis_records
        ):
            raise PortfolioDecisionError("decision lens basis is not typed")
        normalized_basis = tuple(
            sorted(self.basis_records, key=lambda record: record.sort_key)
        )
        if self.basis_records != normalized_basis or len(
            {record.sort_key for record in self.basis_records}
        ) != len(self.basis_records):
            raise PortfolioDecisionError(
                "decision lens basis records must be sorted and unique"
            )
        _ascii("decision lens finding", self.finding)

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "basis_records": [
                record.to_identity_payload() for record in self.basis_records
            ],
            "finding": self.finding,
            "lens": self.lens.value,
            "option_ids": list(self.option_ids),
            "position": self.position.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class QuantTeamDecisionReview:
    """Plural material judgment without seven-role ceremony or scalar scoring."""

    assessments: tuple[DecisionLensAssessment, ...]
    claim_boundary: str
    resolution_basis: str
    disagreement_resolution: str | None = None

    def __post_init__(self) -> None:
        if type(self.assessments) is not tuple or len(self.assessments) < 2:
            raise PortfolioDecisionError(
                "quant-team review requires at least two material lenses"
            )
        if any(
            not isinstance(assessment, DecisionLensAssessment)
            for assessment in self.assessments
        ):
            raise PortfolioDecisionError("quant-team assessment is not typed")
        lens_values = tuple(assessment.lens.value for assessment in self.assessments)
        if lens_values != tuple(sorted(lens_values)) or len(set(lens_values)) != len(
            lens_values
        ):
            raise PortfolioDecisionError(
                "quant-team material lenses must be sorted and unique"
            )
        _ascii("quant-team claim boundary", self.claim_boundary)
        _ascii("quant-team resolution basis", self.resolution_basis)
        has_reservation = any(
            assessment.position
            in {DecisionLensPosition.CHALLENGE, DecisionLensPosition.UNCERTAIN}
            for assessment in self.assessments
        )
        if has_reservation:
            if self.disagreement_resolution is None:
                raise PortfolioDecisionError(
                    "quant-team reservation requires an explicit resolution"
                )
            _ascii(
                "quant-team disagreement resolution",
                self.disagreement_resolution,
            )
        elif self.disagreement_resolution is not None:
            _ascii(
                "quant-team disagreement resolution",
                self.disagreement_resolution,
            )

    def require_options(
        self,
        option_ids: tuple[str, ...],
        *,
        chosen_option_id: str,
    ) -> None:
        known = set(option_ids)
        covered: set[str] = set()
        for assessment in self.assessments:
            if not set(assessment.option_ids).issubset(known):
                raise PortfolioDecisionError(
                    "quant-team review names an unknown Decision option"
                )
            covered.update(assessment.option_ids)
        if covered != known:
            raise PortfolioDecisionError(
                "quant-team review must consider every Decision option"
            )
        if sum(
            chosen_option_id in assessment.option_ids
            for assessment in self.assessments
        ) < 2:
            raise PortfolioDecisionError(
                "chosen allocation requires at least two material lenses"
            )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "assessments": [
                assessment.to_identity_payload()
                for assessment in self.assessments
            ],
            "claim_boundary": self.claim_boundary,
            "disagreement_resolution": self.disagreement_resolution,
            "resolution_basis": self.resolution_basis,
            "schema": "quant_team_decision_review.v1",
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioAxis:
    axis_id: str
    causal_question: str
    mechanism_family: str
    primary_research_layer: ResearchLayer
    system_architecture_family: str
    changed_domains: tuple[ResearchLayer, ...]
    controlled_domains: tuple[ResearchLayer, ...]
    why_now: str
    stop_or_reopen_condition: str
    architecture_chassis: ArchitectureChassisSpec | None = None
    status: str = "open"
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("axis_id", self.axis_id)
        _ascii("causal_question", self.causal_question)
        _ascii("mechanism_family", self.mechanism_family)
        if not isinstance(self.primary_research_layer, ResearchLayer):
            raise PortfolioDecisionError("Portfolio axis research layer is not typed")
        try:
            require_architecture_family(self.system_architecture_family)
        except ResearchGovernanceError as exc:
            raise PortfolioDecisionError(
                "Portfolio axis system architecture family is invalid"
            ) from exc
        if self.architecture_chassis is not None:
            if not isinstance(self.architecture_chassis, ArchitectureChassisSpec):
                raise PortfolioDecisionError(
                    "Portfolio axis architecture chassis is not typed"
                )
            if self.system_architecture_family != self.architecture_chassis.identity:
                raise PortfolioDecisionError(
                    "Portfolio axis family must equal its canonical chassis identity"
                )
        if type(self.changed_domains) is not tuple or not self.changed_domains:
            raise PortfolioDecisionError("Portfolio axis changed_domains are absent")
        if type(self.controlled_domains) is not tuple or not self.controlled_domains:
            raise PortfolioDecisionError("Portfolio axis controlled_domains are absent")
        if any(
            not isinstance(layer, ResearchLayer)
            for layer in (*self.changed_domains, *self.controlled_domains)
        ):
            raise PortfolioDecisionError("Portfolio axis domains are not typed")
        changed = tuple(sorted(self.changed_domains, key=lambda layer: layer.value))
        controlled = tuple(
            sorted(self.controlled_domains, key=lambda layer: layer.value)
        )
        if len(set(changed)) != len(changed) or len(set(controlled)) != len(controlled):
            raise PortfolioDecisionError("Portfolio axis domains must be unique")
        if set(changed).intersection(controlled):
            raise PortfolioDecisionError("changed and controlled domains must be disjoint")
        if self.primary_research_layer not in changed:
            raise PortfolioDecisionError("primary research layer must be changed")
        if (
            self.primary_research_layer is ResearchLayer.SYNTHESIS
            and changed == (ResearchLayer.SYNTHESIS,)
        ):
            if self.architecture_chassis is None:
                raise PortfolioDecisionError(
                    "a pure synthesis axis requires a typed architecture chassis"
                )
            missing_roles = tuple(
                role.value
                for role in ArchitectureRole
                if not getattr(
                    self.architecture_chassis, role.value
                ).component_identities
            )
            if missing_roles:
                raise PortfolioDecisionError(
                    "a pure synthesis axis requires all architecture roles: "
                    + ", ".join(missing_roles)
                )
            represented_decision_domains = {
                component_domain(component)
                for component in self.architecture_chassis.decision.components
            }
            required_controls = {
                ResearchLayer.LABEL,
                ResearchLayer.TRADE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.EXECUTION,
                *represented_decision_domains,
            }
            missing_controls = required_controls.difference(controlled)
            if missing_controls:
                raise PortfolioDecisionError(
                    "a pure synthesis axis lacks required controlled domains: "
                    + ", ".join(
                        sorted(domain.value for domain in missing_controls)
                    )
                )
        elif self.primary_research_layer in {
            ResearchLayer.SYNTHESIS,
            ResearchLayer.PORTFOLIO,
        }:
            if len(changed) < 2:
                raise PortfolioDecisionError(
                    "synthesis or Portfolio axes require multiple changed domains"
                )
        elif changed != (self.primary_research_layer,):
            raise PortfolioDecisionError(
                "a non-synthesis axis must change one primary research layer"
            )
        object.__setattr__(self, "changed_domains", changed)
        object.__setattr__(self, "controlled_domains", controlled)
        _ascii("why_now", self.why_now)
        _ascii("stop_or_reopen_condition", self.stop_or_reopen_condition)
        if self.status not in {"open", "preserved", "deferred", "pruned"}:
            raise PortfolioDecisionError("Portfolio axis status is not typed")
        identity_payload: dict[str, CanonicalValue] = {
            "axis_id": self.axis_id,
            "causal_question": self.causal_question,
            "changed_domains": [layer.value for layer in changed],
            "controlled_domains": [layer.value for layer in controlled],
            "mechanism_family": self.mechanism_family,
            "primary_research_layer": self.primary_research_layer.value,
            "schema": (
                "portfolio_axis.v2"
                if self.architecture_chassis is None
                else "portfolio_axis.v3"
            ),
            "stop_or_reopen_condition": self.stop_or_reopen_condition,
            "system_architecture_family": self.system_architecture_family,
            "why_now": self.why_now,
        }
        if self.architecture_chassis is not None:
            identity_payload["architecture_chassis"] = (
                self.architecture_chassis.to_identity_payload()
            )
        object.__setattr__(
            self,
            "identity",
            "axis:"
            + canonical_digest(
                domain="portfolio-axis",
                payload=identity_payload,
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioSnapshot:
    mission_id: str
    axes: tuple[PortfolioAxis, ...]
    opportunity_cost_basis: str
    research_intake_id: str | None = None
    exhaustion_standard: InitVar[object] = None
    _exhaustion_standard_bytes: bytes = field(init=False, repr=False, compare=False)
    identity: str = field(init=False)

    def __post_init__(self, exhaustion_standard: object) -> None:
        _ascii("mission_id", self.mission_id)
        _ascii("opportunity_cost_basis", self.opportunity_cost_basis)
        if self.research_intake_id is not None:
            _ascii("research_intake_id", self.research_intake_id)
            if (
                not self.research_intake_id.startswith("research-intake:")
                or len(self.research_intake_id) != 80
            ):
                raise PortfolioDecisionError("research_intake_id is invalid")
        if type(self.axes) is not tuple or len(self.axes) < 2:
            raise PortfolioDecisionError(
                "Portfolio snapshot requires at least two structural axes"
            )
        axes = tuple(sorted(self.axes, key=lambda axis: axis.axis_id))
        object.__setattr__(self, "axes", axes)
        axis_ids = [axis.axis_id for axis in axes]
        if len(set(axis_ids)) != len(axis_ids):
            raise PortfolioDecisionError("Portfolio axis identities must be unique")
        declared_families = {axis.mechanism_family for axis in axes}
        if len(declared_families) < 2:
            raise PortfolioDecisionError(
                "Portfolio snapshot must preserve unrelated mechanism families"
            )
        if exhaustion_standard is not None:
            if type(exhaustion_standard) is not dict or set(exhaustion_standard) != {
                "minimum_axes",
                "minimum_distinct_studies_per_axis",
                "minimum_mechanism_families",
                "minimum_negative_executables_per_family",
                "minimum_primary_research_layers",
                "minimum_system_architecture_families",
                "architecture_review_minimum_studies",
                "architecture_review_minimum_axes",
                "required_evidence_modes",
                "stop_basis",
            }:
                raise PortfolioDecisionError("exhaustion standard schema is invalid")
            for name in (
                "minimum_axes",
                "minimum_distinct_studies_per_axis",
                "minimum_mechanism_families",
                "minimum_negative_executables_per_family",
                "minimum_primary_research_layers",
                "minimum_system_architecture_families",
                "architecture_review_minimum_studies",
                "architecture_review_minimum_axes",
            ):
                value = exhaustion_standard[name]
                if type(value) is not int or value <= 0:
                    raise PortfolioDecisionError(
                        "exhaustion standard bounds must be positive integers"
                    )
            if (
                exhaustion_standard["minimum_axes"]
                < exhaustion_standard["minimum_mechanism_families"]
                or exhaustion_standard["minimum_mechanism_families"] < 3
                or exhaustion_standard["minimum_distinct_studies_per_axis"] < 2
                or exhaustion_standard["minimum_negative_executables_per_family"] < 2
                or exhaustion_standard["minimum_primary_research_layers"] < 3
                or exhaustion_standard["minimum_system_architecture_families"] < 2
                or exhaustion_standard["minimum_axes"]
                < exhaustion_standard["minimum_primary_research_layers"]
                or exhaustion_standard["architecture_review_minimum_axes"] < 2
                or exhaustion_standard["architecture_review_minimum_studies"]
                < exhaustion_standard["architecture_review_minimum_axes"]
            ):
                raise PortfolioDecisionError(
                    "exhaustion standard is too shallow for a scientific terminal"
                )
            modes = exhaustion_standard["required_evidence_modes"]
            allowed_modes = {
                "ablation",
                "causal_contrast",
                "cost_and_execution",
                "extreme_or_boundary",
                "neighborhood",
                "regime_stability",
                "sensitivity_or_stress",
                "temporal_stability",
            }
            required_core = {
                "causal_contrast",
                "cost_and_execution",
                "sensitivity_or_stress",
            }
            if (
                not isinstance(modes, list)
                or len(set(modes)) != len(modes)
                or not required_core.issubset(modes)
                or not set(modes).issubset(allowed_modes)
            ):
                raise PortfolioDecisionError(
                    "exhaustion standard lacks diverse typed evidence modes"
                )
            _ascii("exhaustion stop_basis", exhaustion_standard["stop_basis"])
            exhaustion_standard = {
                **exhaustion_standard,
                "required_evidence_modes": sorted(modes),
            }
        standard_bytes = canonical_bytes(exhaustion_standard)
        object.__setattr__(
            self, "_exhaustion_standard_bytes", standard_bytes
        )
        identity = canonical_digest(
            domain="portfolio-snapshot", payload=self.to_identity_payload()
        )
        object.__setattr__(self, "identity", f"portfolio:{identity}")

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "axes": [
                {
                    "axis_id": axis.axis_id,
                    "axis_identity": axis.identity,
                    "architecture_chassis": (
                        None
                        if axis.architecture_chassis is None
                        else axis.architecture_chassis.to_identity_payload()
                    ),
                    "architecture_chassis_identity": (
                        None
                        if axis.architecture_chassis is None
                        else axis.architecture_chassis.identity
                    ),
                    "causal_question": axis.causal_question,
                    "changed_domains": [
                        layer.value for layer in axis.changed_domains
                    ],
                    "controlled_domains": [
                        layer.value for layer in axis.controlled_domains
                    ],
                    "mechanism_family": axis.mechanism_family,
                    "primary_research_layer": axis.primary_research_layer.value,
                    "status": axis.status,
                    "stop_or_reopen_condition": axis.stop_or_reopen_condition,
                    "system_architecture_family": axis.system_architecture_family,
                    "why_now": axis.why_now,
                }
                for axis in self.axes
            ],
            "exhaustion_standard": self.exhaustion_standard_value(),
            "mission_id": self.mission_id,
            "opportunity_cost_basis": self.opportunity_cost_basis,
            "research_intake_id": self.research_intake_id,
            "schema": "portfolio_snapshot.v3",
        }

    def exhaustion_standard_value(self) -> CanonicalValue:
        return parse_canonical(self._exhaustion_standard_bytes)


class PortfolioAction(str, Enum):
    PRESERVE = "preserve"
    PRUNE = "prune"
    DEEPEN = "deepen"
    CONTRAST = "contrast"
    ROTATE = "rotate"
    NEW_MECHANISM = "new_mechanism"
    COMPLEMENTARY_SLEEVE = "complementary_sleeve"
    RECOMBINE = "recombine"
    SYNTHESIZE = "synthesize"


_DIVERSIFYING_ACTIONS = frozenset(
    {
        PortfolioAction.ROTATE,
        PortfolioAction.CONTRAST,
        PortfolioAction.NEW_MECHANISM,
        PortfolioAction.COMPLEMENTARY_SLEEVE,
        PortfolioAction.RECOMBINE,
        PortfolioAction.SYNTHESIZE,
    }
)


_ADAPTIVE_BASIS_FIELDS = frozenset(
    {
        "uncertainty",
        "causal_complexity",
        "surface_curvature",
        "compute_cost",
        "expected_information_value",
        "portfolio_opportunity_cost",
    }
)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be str")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if not value.isascii():
        raise ValueError(f"{name} must be ASCII")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchSpec:
    """One immutable, operator-selected adaptive Batch bound.

    The type enforces a positive finite bound but deliberately imposes no
    project-wide small maximum on trials or compute.
    """

    batch_id: str = field(compare=False)
    study_id: str = field(compare=False)
    study_hash: str = field(compare=False)
    display_name: str = field(compare=False)
    max_trials: int = field(compare=False)
    max_compute_seconds: int = field(compare=False)
    max_wall_seconds: int = field(compare=False)
    stop_rule: str = field(compare=False)
    source_contract_ids: tuple[str, ...] = field(default=(), compare=False)
    concurrent_family: ConcurrentFamilyManifest | None = field(
        default=None,
        compare=False,
    )
    acceptance_profile: InitVar[object]
    adaptive_basis: InitVar[object]
    _acceptance_bytes: bytes = field(init=False, repr=False, compare=False)
    _basis_bytes: bytes = field(init=False, repr=False, compare=False)
    identity: str = field(init=False)

    def __post_init__(
        self,
        acceptance_profile: object,
        adaptive_basis: object,
    ) -> None:
        _ascii("batch_id", self.batch_id)
        _ascii("study_id", self.study_id)
        study_hash = _ascii("study_hash", self.study_hash)
        if len(study_hash) != 64 or any(
            character not in "0123456789abcdef" for character in study_hash
        ):
            raise BatchSpecError("study_hash must be a lowercase SHA-256 digest")
        _ascii("display_name", self.display_name)
        _ascii("stop_rule", self.stop_rule)
        sources = tuple(sorted(_ascii("source_contract_id", item) for item in self.source_contract_ids))
        if len(set(sources)) != len(sources):
            raise BatchSpecError("source_contract_ids must be unique")
        object.__setattr__(self, "source_contract_ids", sources)
        for name in ("max_trials", "max_compute_seconds", "max_wall_seconds"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise BatchSpecError(f"{name} must be a positive int")

        if type(adaptive_basis) is not dict:
            raise BatchSpecError("adaptive_basis must be a canonical object")
        missing = _ADAPTIVE_BASIS_FIELDS.difference(adaptive_basis)
        if missing:
            raise BatchSpecError(
                "adaptive_basis is missing: " + ", ".join(sorted(missing))
            )
        if type(acceptance_profile) is not dict or not acceptance_profile:
            raise BatchSpecError("acceptance_profile must be a non-empty object")

        acceptance_payload = dict(acceptance_profile)
        if "concurrent_family" in acceptance_payload:
            raise BatchSpecError(
                "concurrent_family is reserved for the typed Batch manifest"
            )
        declared_family_size = acceptance_payload.pop(
            "concurrent_family_size", None
        )
        if self.concurrent_family is None:
            if declared_family_size is not None:
                raise BatchSpecError(
                    "concurrent_family_size requires a typed concurrent family manifest"
                )
        else:
            if not isinstance(self.concurrent_family, ConcurrentFamilyManifest):
                raise BatchSpecError("concurrent_family must be a typed manifest")
            if (
                declared_family_size is not None
                and declared_family_size != self.concurrent_family.family_size
            ):
                raise BatchSpecError(
                    "acceptance family size differs from the exact typed manifest"
                )
            if self.max_trials != self.concurrent_family.family_size:
                raise BatchSpecError(
                    "concurrent family size must equal the frozen Batch trial bound"
                )
            acceptance_payload["concurrent_family"] = (
                self.concurrent_family.to_identity_payload()
            )

        acceptance_bytes = canonical_bytes(acceptance_payload)
        basis_bytes = canonical_bytes(adaptive_basis)
        object.__setattr__(self, "_acceptance_bytes", acceptance_bytes)
        object.__setattr__(self, "_basis_bytes", basis_bytes)
        batch_digest = canonical_digest(
            domain="batch-spec",
            payload=self.to_identity_payload(),
        )
        object.__setattr__(self, "identity", f"batch:{batch_digest}")

    def acceptance(self) -> CanonicalValue:
        return parse_canonical(self._acceptance_bytes)

    def basis(self) -> CanonicalValue:
        return parse_canonical(self._basis_bytes)

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "acceptance_profile": self.acceptance(),
            "adaptive_basis": self.basis(),
            "max_compute_seconds": self.max_compute_seconds,
            "max_trials": self.max_trials,
            "max_wall_seconds": self.max_wall_seconds,
            "schema": "batch_spec.v1",
            "source_contract_ids": list(self.source_contract_ids),
            "stop_rule": self.stop_rule,
            "study_hash": self.study_hash,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionOption:
    option_id: str
    action: PortfolioAction
    target_id: str
    expected_information_value: str
    opportunity_cost: str
    omission_reason: str | None = None

    def __post_init__(self) -> None:
        _ascii("option_id", self.option_id)
        _ascii("target_id", self.target_id)
        _ascii("expected_information_value", self.expected_information_value)
        _ascii("opportunity_cost", self.opportunity_cost)
        if not isinstance(self.action, PortfolioAction):
            raise TypeError("action must be PortfolioAction")
        if self.omission_reason is not None:
            _ascii("omission_reason", self.omission_reason)


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioDecision:
    """One bounded decision that cannot lock the forest after a recent win."""

    decision_id: str
    chosen_option_id: str
    options: tuple[DecisionOption, ...]
    rationale: str
    commitment_batches: int
    quant_team_review: QuantTeamDecisionReview | None = None
    baseline_executable: ExecutableSpec | None = field(default=None, repr=False)
    replay_obligation_ids: tuple[str, ...] = ()
    recent_positive_lineage_id: str | None = None
    locks_future_portfolio: bool = False
    architecture_chassis: ArchitectureChassisSpec | None = field(init=False, repr=False)
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("decision_id", self.decision_id)
        _ascii("chosen_option_id", self.chosen_option_id)
        _ascii("rationale", self.rationale)
        if type(self.options) is not tuple:
            raise PortfolioDecisionError("options must be a frozen tuple")
        if not self.options:
            raise PortfolioDecisionError("a decision requires at least one option")
        options = tuple(sorted(self.options, key=lambda option: option.option_id))
        object.__setattr__(self, "options", options)
        option_ids = tuple(option.option_id for option in options)
        if len(set(option_ids)) != len(option_ids):
            raise PortfolioDecisionError("option_id values must be unique")
        if self.chosen_option_id not in option_ids:
            raise PortfolioDecisionError("chosen_option_id is not present")
        if self.quant_team_review is not None:
            if not isinstance(self.quant_team_review, QuantTeamDecisionReview):
                raise PortfolioDecisionError("quant_team_review is not typed")
            self.quant_team_review.require_options(
                option_ids,
                chosen_option_id=self.chosen_option_id,
            )
        if type(self.commitment_batches) is not int or self.commitment_batches <= 0:
            raise PortfolioDecisionError(
                "commitment_batches must be a positive finite int"
            )
        if self.locks_future_portfolio:
            raise PortfolioDecisionError("a decision cannot lock the future Portfolio")
        if len(self.options) < 2:
            raise PortfolioDecisionError(
                "a material Portfolio decision must compare at least two alternatives"
            )
        if not any(
            option.action in _DIVERSIFYING_ACTIONS for option in self.options
        ):
            raise PortfolioDecisionError(
                "a material Portfolio decision must retain a structurally "
                "diversifying action"
            )
        if self.recent_positive_lineage_id is not None:
            _ascii("recent_positive_lineage_id", self.recent_positive_lineage_id)
            if len(self.options) < 2:
                raise PortfolioDecisionError(
                    "recent-positive work must compare a non-monopoly alternative"
                )
            if not any(
                option.action in _DIVERSIFYING_ACTIONS for option in self.options
            ):
                raise PortfolioDecisionError(
                    "recent-positive work must retain a diversifying alternative"
                )

        if self.baseline_executable is not None and not isinstance(
            self.baseline_executable, ExecutableSpec
        ):
            raise PortfolioDecisionError(
                "Portfolio Decision baseline must be an ExecutableSpec"
            )
        if type(self.replay_obligation_ids) is not tuple:
            raise PortfolioDecisionError(
                "replay_obligation_ids must be a frozen tuple"
            )
        replay_obligation_ids = tuple(sorted(self.replay_obligation_ids))
        if len(replay_obligation_ids) != len(set(replay_obligation_ids)):
            raise PortfolioDecisionError("replay obligation identities must be unique")
        for obligation_id in replay_obligation_ids:
            if type(obligation_id) is not str or not obligation_id.isascii():
                raise PortfolioDecisionError("replay obligation identity is invalid")
            digest = obligation_id.removeprefix("historical-replay-obligation:")
            if obligation_id == digest or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise PortfolioDecisionError("replay obligation identity is invalid")
        object.__setattr__(
            self, "replay_obligation_ids", replay_obligation_ids
        )
        architecture = (
            None
            if self.baseline_executable is None
            else ArchitectureChassisSpec.from_executable(self.baseline_executable)
        )
        object.__setattr__(self, "architecture_chassis", architecture)

        for option in self.options:
            if (
                option.option_id != self.chosen_option_id
                and option.omission_reason is None
            ):
                raise PortfolioDecisionError(
                    f"unchosen option {option.option_id} needs an omission reason"
                )

        decision_digest = canonical_digest(
            domain="portfolio-decision",
            payload=self.to_identity_payload(),
        )
        object.__setattr__(self, "identity", f"decision:{decision_digest}")

    @property
    def chosen(self) -> DecisionOption:
        return next(
            option
            for option in self.options
            if option.option_id == self.chosen_option_id
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        payload: dict[str, CanonicalValue] = {
            "architecture_chassis": (
                None
                if self.architecture_chassis is None
                else self.architecture_chassis.to_identity_payload()
            ),
            "architecture_chassis_identity": (
                None
                if self.architecture_chassis is None
                else self.architecture_chassis.identity
            ),
            "baseline_executable": (
                None
                if self.baseline_executable is None
                else self.baseline_executable.to_identity_payload()
            ),
            "baseline_executable_id": (
                None
                if self.baseline_executable is None
                else self.baseline_executable.identity
            ),
            "chosen_option_id": self.chosen_option_id,
            "commitment_batches": self.commitment_batches,
            "decision_id": self.decision_id,
            "locks_future_portfolio": self.locks_future_portfolio,
            "options": [
                {
                    "action": option.action.value,
                    "expected_information_value": option.expected_information_value,
                    "omission_reason": option.omission_reason,
                    "opportunity_cost": option.opportunity_cost,
                    "option_id": option.option_id,
                    "target_id": option.target_id,
                }
                for option in self.options
            ],
            "rationale": self.rationale,
            "recent_positive_lineage_id": self.recent_positive_lineage_id,
            "schema": (
                "portfolio_decision.v3"
                if self.quant_team_review is not None
                else (
                    "portfolio_decision.v1"
                    if self.baseline_executable is None
                    else "portfolio_decision.v2"
                )
            ),
        }
        if self.quant_team_review is not None:
            payload["quant_team_review"] = (
                self.quant_team_review.to_identity_payload()
            )
        # Preserve byte-for-byte legacy identities unless a Decision actually
        # binds typed historical replay work.
        if self.replay_obligation_ids:
            payload["replay_obligation_ids"] = list(self.replay_obligation_ids)
        return payload


DecisionKind = PortfolioAction


__all__ = [
    "BatchSpec",
    "BatchSpecError",
    "ConcurrentFamilyEvaluationMode",
    "ConcurrentFamilyManifest",
    "DecisionKind",
    "DecisionBasisRecord",
    "DecisionLens",
    "DecisionLensAssessment",
    "DecisionLensPosition",
    "DecisionOption",
    "PortfolioAction",
    "PortfolioAxis",
    "PortfolioDecision",
    "PortfolioDecisionError",
    "QuantTeamDecisionReview",
    "PortfolioSnapshot",
]
