"""Pure autonomous-research governance primitives for V2 harness proof.

The module contains no market hypothesis and performs no I/O. It defines an
empty generic research map, hypothesis and Scout routing schemas, scoped
negative memory, deterministic anti-loop guards, and a recorded scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.dispatch import PROGRAM_KINDS


RESEARCH_STATES = (
    "unseen",
    "shallow",
    "contextual",
    "deepened",
    "refuted",
    "synthesis_ready",
)
GENERIC_DIMENSIONS = (
    "feature",
    "label",
    "model",
    "calibration",
    "selector",
    "trade",
    "sizing",
    "portfolio_risk",
    "direction",
    "regime",
    "session",
    "lifecycle",
    "synthesis",
)
HYPOTHESIS_TYPES = frozenset(
    {"structural_batch", "coupled_mechanism", "synthesis_ablation"}
)
SCOUT_MODES = frozenset({"s_breadth", "s_depth", "s_synthesis"})
SCIENTIFIC_DISPOSITIONS = frozenset(
    {
        "promising",
        "contextual",
        "complementary",
        "unstable",
        "unidentified",
        "dead",
        "broken_execution",
    }
)
NEGATIVE_STRENGTHS = frozenset(
    {"shallow_negative", "orthogonal_negative", "family_refuted"}
)
REQUIRED_CONTEXT_FIELDS = frozenset(
    {
        "program_bundle_sha256",
        "data_identity_sha256",
        "split_identity_sha256",
        "cost_identity_sha256",
        "direction_context",
        "session_context",
        "regime_context",
        "lifecycle_context",
    }
)
FORBIDDEN_PROVENANCE_KEYS = frozenset(
    {
        "inherited_from",
        "legacy_source",
        "prior_project",
        "prior_stage_id",
        "prior_run_id",
        "prior_kpi",
        "source_project",
        "seed_priority",
        "predecessor_campaign",
    }
)
FORBIDDEN_PROVENANCE_PATTERNS = (
    re.compile(r"obsidian", re.IGNORECASE),
    re.compile(r"axiom(?:[_ -]?rift)?[_ -]?v1", re.IGNORECASE),
    re.compile(r"\bc0144\b", re.IGNORECASE),
    re.compile(r"\bsc[0-9]{4}\b", re.IGNORECASE),
    re.compile(r"\bc[0-9]{4}\b", re.IGNORECASE),
    re.compile(r"\bstage[_ -]?[0-9]+\b", re.IGNORECASE),
    re.compile(r"\brun[_ -]?[0-9]+\b", re.IGNORECASE),
)
RECENT_AXIS_WINDOW = 5
RECENT_AXIS_MAX = 2


class AutonomyGuardError(ValueError):
    """Raised when an autonomous research record violates hard governance."""


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _safe_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
        raise AutonomyGuardError(f"{label} must be a safe lowercase identifier")
    return value


def _bounded_score(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AutonomyGuardError(f"{label} must be numeric")
    observed = float(value)
    if not math.isfinite(observed) or observed < 0.0 or observed > 1.0:
        raise AutonomyGuardError(f"{label} must be between zero and one")
    return observed


def assert_no_scientific_inheritance(payload: Any) -> None:
    """Reject scientific provenance from outside the active empty epoch."""

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for raw_key, item in value.items():
                key = str(raw_key).lower()
                if key in FORBIDDEN_PROVENANCE_KEYS:
                    raise AutonomyGuardError(f"forbidden scientific provenance key: {path}{key}")
                walk(item, f"{path}{key}.")
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for index, item in enumerate(value):
                walk(item, f"{path}{index}.")
            return
        if isinstance(value, str):
            for pattern in FORBIDDEN_PROVENANCE_PATTERNS:
                if pattern.search(value):
                    raise AutonomyGuardError(
                        f"forbidden scientific provenance value at {path.rstrip('.')}"
                    )

    walk(payload, "")


@dataclass(frozen=True)
class ResearchAxis:
    axis_id: str
    dimension: str
    state: str = "unseen"
    evidence_ids: tuple[str, ...] = ()
    concrete_observations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _safe_identifier(self.axis_id, "axis_id")
        if self.dimension not in GENERIC_DIMENSIONS:
            raise AutonomyGuardError(f"unsupported generic dimension: {self.dimension}")
        if self.state not in RESEARCH_STATES:
            raise AutonomyGuardError(f"invalid research state: {self.state}")
        if not all(isinstance(value, str) and value for value in self.evidence_ids):
            raise AutonomyGuardError("research axis evidence ids must be nonempty strings")
        if not all(isinstance(value, str) and value for value in self.concrete_observations):
            raise AutonomyGuardError("research observations must be nonempty strings")
        if self.state == "unseen" and (self.evidence_ids or self.concrete_observations):
            raise AutonomyGuardError("unseen research axes cannot contain scientific evidence")
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(self.evidence_ids)))
        object.__setattr__(
            self,
            "concrete_observations",
            tuple(dict.fromkeys(self.concrete_observations)),
        )


@dataclass(frozen=True)
class ResearchMap:
    axes: Mapping[str, ResearchAxis]
    scientific_epoch_id: str | None = None

    def __post_init__(self) -> None:
        normalized: dict[str, ResearchAxis] = {}
        for key, axis in self.axes.items():
            if not isinstance(axis, ResearchAxis) or key != axis.axis_id:
                raise AutonomyGuardError("research map axis key differs from identity")
            if axis.dimension in {item.dimension for item in normalized.values()}:
                raise AutonomyGuardError("research map dimensions must be unique")
            normalized[key] = axis
        if set(item.dimension for item in normalized.values()) != set(GENERIC_DIMENSIONS):
            raise AutonomyGuardError("research map must cover only all generic dimensions")
        if self.scientific_epoch_id is not None and not re.fullmatch(
            r"V2EPOCH[0-9]{4}", self.scientific_epoch_id
        ):
            raise AutonomyGuardError("scientific epoch identity is invalid")
        object.__setattr__(self, "axes", MappingProxyType(normalized))
        assert_no_scientific_inheritance(self.to_payload())

    @classmethod
    def empty(cls) -> "ResearchMap":
        return cls(
            {
                f"axis_{dimension}": ResearchAxis(
                    axis_id=f"axis_{dimension}",
                    dimension=dimension,
                )
                for dimension in GENERIC_DIMENSIONS
            }
        )

    @classmethod
    def for_epoch(cls, scientific_epoch_id: str) -> "ResearchMap":
        return cls(
            {
                f"axis_{dimension}": ResearchAxis(
                    axis_id=f"axis_{dimension}",
                    dimension=dimension,
                )
                for dimension in GENERIC_DIMENSIONS
            },
            scientific_epoch_id=scientific_epoch_id,
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ResearchMap":
        if not isinstance(payload, Mapping) or payload.get("schema") not in {
            "axiom_rift_v2_empty_research_map_v1",
            "axiom_rift_v2_research_map_v1",
        }:
            raise AutonomyGuardError("research map payload schema is invalid")
        expected_fields = {"schema", "scientific_epoch_id", "axes"}
        if payload.get("schema") == "axiom_rift_v2_empty_research_map_v1":
            expected_fields = {"schema", "axes"}
        if set(payload) != expected_fields:
            raise AutonomyGuardError("research map payload fields are invalid")
        rows = payload.get("axes")
        if not isinstance(rows, list):
            raise AutonomyGuardError("research map payload axes must be a list")
        axes: dict[str, ResearchAxis] = {}
        try:
            for row in rows:
                if not isinstance(row, Mapping):
                    raise TypeError("axis row is not a mapping")
                if set(row) != {
                    "axis_id",
                    "dimension",
                    "state",
                    "evidence_ids",
                    "concrete_observations",
                }:
                    raise TypeError("axis row fields are invalid")
                axis = ResearchAxis(
                    axis_id=str(row["axis_id"]),
                    dimension=str(row["dimension"]),
                    state=str(row["state"]),
                    evidence_ids=tuple(row.get("evidence_ids", [])),
                    concrete_observations=tuple(
                        row.get("concrete_observations", [])
                    ),
                )
                axes[axis.axis_id] = axis
            epoch = payload.get("scientific_epoch_id")
            return cls(
                axes,
                scientific_epoch_id=None if epoch is None else str(epoch),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AutonomyGuardError(
                f"research map payload is invalid: {exc}"
            ) from exc

    def with_axis_observation(
        self,
        *,
        axis_id: str,
        state: str,
        evidence_id: str,
        observation: str,
    ) -> "ResearchMap":
        current = self.axes.get(axis_id)
        if current is None:
            raise AutonomyGuardError(
                f"research map observation axis is absent: {axis_id}"
            )
        updated = ResearchAxis(
            axis_id=current.axis_id,
            dimension=current.dimension,
            state=state,
            evidence_ids=(*current.evidence_ids, evidence_id),
            concrete_observations=(
                *current.concrete_observations,
                observation,
            ),
        )
        axes = dict(self.axes)
        axes[axis_id] = updated
        return ResearchMap(axes, scientific_epoch_id=self.scientific_epoch_id)

    @property
    def is_empty(self) -> bool:
        return self.scientific_epoch_id is None and all(
            axis.state == "unseen"
            and not axis.evidence_ids
            and not axis.concrete_observations
            for axis in self.axes.values()
        )

    def coverage_deficit(self, axis_id: str) -> float:
        axis = self.axes.get(axis_id)
        if axis is None:
            raise AutonomyGuardError(f"proposal axis is absent from research map: {axis_id}")
        return {
            "unseen": 1.0,
            "shallow": 0.75,
            "contextual": 0.5,
            "synthesis_ready": 0.5,
            "deepened": 0.25,
            "refuted": 0.0,
        }[axis.state]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_research_map_v1",
            "scientific_epoch_id": self.scientific_epoch_id,
            "axes": [
                {
                    "axis_id": axis.axis_id,
                    "dimension": axis.dimension,
                    "state": axis.state,
                    "evidence_ids": list(axis.evidence_ids),
                    "concrete_observations": list(axis.concrete_observations),
                }
                for axis in sorted(self.axes.values(), key=lambda item: item.axis_id)
            ],
        }


@dataclass(frozen=True)
class NumericKnob:
    path: str
    low: float
    baseline: float
    high: float

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or self.path.count(".") < 1:
            raise AutonomyGuardError("numeric knob path must identify a program parameter")
        values = (self.low, self.baseline, self.high)
        if not all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            for value in values
        ):
            raise AutonomyGuardError("numeric knob values must be finite")
        if not float(self.low) < float(self.baseline) < float(self.high):
            raise AutonomyGuardError("numeric knob requires low < baseline < high")


@dataclass(frozen=True)
class HypothesisBatch:
    hypothesis_id: str
    family_id: str
    hypothesis_type: str
    dominant_axis: str
    scientific_epoch_id: str
    scout_mode: str
    bundle_roles: Mapping[str, str]
    semantic_signature_sha256: str
    parent_evidence_ids: tuple[str, ...] = ()
    coupled_program_kinds: tuple[str, ...] = ()
    numeric_knobs: tuple[NumericKnob, ...] = ()
    local_calibration_rounds: int = 0
    automatic_range_extensions: int = 0

    def __post_init__(self) -> None:
        if re.fullmatch(r"V2H[0-9]{4}", self.hypothesis_id) is None:
            raise AutonomyGuardError("hypothesis identity is invalid")
        _safe_identifier(self.family_id, "family_id")
        if self.hypothesis_type not in HYPOTHESIS_TYPES:
            raise AutonomyGuardError("hypothesis type is invalid")
        _safe_identifier(self.dominant_axis, "dominant_axis")
        if re.fullmatch(r"V2EPOCH[0-9]{4}", self.scientific_epoch_id) is None:
            raise AutonomyGuardError("hypothesis requires an active scientific epoch")
        if self.scout_mode not in SCOUT_MODES:
            raise AutonomyGuardError("hypothesis Scout mode is invalid")
        roles = dict(self.bundle_roles)
        if not roles or any(
            not isinstance(role, str)
            or not role
            or not _is_sha256(bundle_hash)
            for role, bundle_hash in roles.items()
        ):
            raise AutonomyGuardError("bundle roles require named sha256 identities")
        hashes = list(roles.values())
        if len(hashes) != len(set(hashes)):
            raise AutonomyGuardError("hypothesis bundles must be materially distinct")
        if not _is_sha256(self.semantic_signature_sha256):
            raise AutonomyGuardError("semantic signature must be a lowercase sha256")
        if len(self.numeric_knobs) > 2:
            raise AutonomyGuardError("a hypothesis may register at most two numeric knobs")
        if len({knob.path for knob in self.numeric_knobs}) != len(self.numeric_knobs):
            raise AutonomyGuardError("numeric knob paths must be unique")
        if self.local_calibration_rounds not in {0, 1}:
            raise AutonomyGuardError("local calibration is limited to one round")
        if self.automatic_range_extensions != 0:
            raise AutonomyGuardError("automatic numeric range extension is forbidden")
        if self.hypothesis_type == "structural_batch":
            if self.scout_mode != "s_breadth" or not 3 <= len(roles) <= 5:
                raise AutonomyGuardError(
                    "structural batch requires S-Breadth and three to five bundles"
                )
        elif self.hypothesis_type == "coupled_mechanism":
            if self.scout_mode not in {"s_breadth", "s_depth"} or not 2 <= len(roles) <= 5:
                raise AutonomyGuardError("coupled mechanism requires two to five bundles")
            kinds = tuple(dict.fromkeys(self.coupled_program_kinds))
            if len(kinds) < 2 or any(kind not in PROGRAM_KINDS for kind in kinds):
                raise AutonomyGuardError(
                    "coupled mechanism requires at least two registered program kinds"
                )
        else:
            required_roles = {"parent_a", "parent_b", "combined", "ablation"}
            if self.scout_mode != "s_synthesis" or set(roles) != required_roles:
                raise AutonomyGuardError(
                    "synthesis requires parent A, parent B, combined, and ablation bundles"
                )
            if len(set(self.parent_evidence_ids)) < 2:
                raise AutonomyGuardError("synthesis requires two new-epoch parent receipts")
        if self.hypothesis_type != "synthesis_ablation" and self.parent_evidence_ids:
            raise AutonomyGuardError("only synthesis may declare parent evidence")
        object.__setattr__(self, "bundle_roles", MappingProxyType(roles))
        object.__setattr__(
            self,
            "parent_evidence_ids",
            tuple(dict.fromkeys(self.parent_evidence_ids)),
        )
        object.__setattr__(
            self,
            "coupled_program_kinds",
            tuple(dict.fromkeys(self.coupled_program_kinds)),
        )
        object.__setattr__(self, "numeric_knobs", tuple(self.numeric_knobs))
        assert_no_scientific_inheritance(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_hypothesis_batch_v1",
            "scientific_origin": "v2_current",
            "hypothesis_id": self.hypothesis_id,
            "family_id": self.family_id,
            "hypothesis_type": self.hypothesis_type,
            "dominant_axis": self.dominant_axis,
            "scientific_epoch_id": self.scientific_epoch_id,
            "scout_mode": self.scout_mode,
            "bundle_roles": dict(self.bundle_roles),
            "semantic_signature_sha256": self.semantic_signature_sha256,
            "parent_evidence_ids": list(self.parent_evidence_ids),
            "coupled_program_kinds": list(self.coupled_program_kinds),
            "numeric_knobs": [
                {
                    "path": knob.path,
                    "low": knob.low,
                    "baseline": knob.baseline,
                    "high": knob.high,
                }
                for knob in self.numeric_knobs
            ],
            "local_calibration_rounds": self.local_calibration_rounds,
            "automatic_range_extensions": self.automatic_range_extensions,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "HypothesisBatch":
        if payload.get("schema") != "axiom_rift_v2_hypothesis_batch_v1":
            raise AutonomyGuardError("hypothesis batch schema is invalid")
        if payload.get("scientific_origin") != "v2_current":
            raise AutonomyGuardError("hypothesis batch scientific origin is invalid")
        assert_no_scientific_inheritance(payload)
        knobs = payload.get("numeric_knobs", [])
        if not isinstance(knobs, list):
            raise AutonomyGuardError("hypothesis numeric knobs must be a list")
        try:
            parsed_knobs = tuple(
                NumericKnob(
                    path=str(item["path"]),
                    low=float(item["low"]),
                    baseline=float(item["baseline"]),
                    high=float(item["high"]),
                )
                for item in knobs
            )
            return cls(
                hypothesis_id=str(payload["hypothesis_id"]),
                family_id=str(payload["family_id"]),
                hypothesis_type=str(payload["hypothesis_type"]),
                dominant_axis=str(payload["dominant_axis"]),
                scientific_epoch_id=str(payload["scientific_epoch_id"]),
                scout_mode=str(payload["scout_mode"]),
                bundle_roles=dict(payload["bundle_roles"]),
                semantic_signature_sha256=str(payload["semantic_signature_sha256"]),
                parent_evidence_ids=tuple(payload.get("parent_evidence_ids", [])),
                coupled_program_kinds=tuple(payload.get("coupled_program_kinds", [])),
                numeric_knobs=parsed_knobs,
                local_calibration_rounds=int(payload.get("local_calibration_rounds", 0)),
                automatic_range_extensions=int(payload.get("automatic_range_extensions", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AutonomyGuardError(f"hypothesis batch payload is invalid: {exc}") from exc


@dataclass(frozen=True)
class ScopedNegativeMemory:
    hypothesis_id: str
    family_id: str
    strength: str
    evidence_ids: tuple[str, ...]
    tested_context: Mapping[str, Any]
    untested_contexts: tuple[str, ...]
    do_not_retry_hashes: tuple[str, ...]
    orthogonal_context_hashes: tuple[str, ...] = ()
    identification_impossible: bool = False
    identification_receipt_id: str | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(r"V2H[0-9]{4}", self.hypothesis_id) is None:
            raise AutonomyGuardError("negative memory hypothesis identity is invalid")
        _safe_identifier(self.family_id, "family_id")
        if self.strength not in NEGATIVE_STRENGTHS:
            raise AutonomyGuardError("negative memory strength is invalid")
        if not self.evidence_ids or not all(
            isinstance(value, str) and value for value in self.evidence_ids
        ):
            raise AutonomyGuardError("negative memory requires evidence receipts")
        context = dict(self.tested_context)
        if set(context) != REQUIRED_CONTEXT_FIELDS:
            raise AutonomyGuardError("negative memory context surface is incomplete")
        for key in (
            "program_bundle_sha256",
            "data_identity_sha256",
            "split_identity_sha256",
            "cost_identity_sha256",
        ):
            if not _is_sha256(context[key]):
                raise AutonomyGuardError(f"negative memory context hash is invalid: {key}")
        for key in REQUIRED_CONTEXT_FIELDS - {
            "program_bundle_sha256",
            "data_identity_sha256",
            "split_identity_sha256",
            "cost_identity_sha256",
        }:
            if not isinstance(context[key], str) or not context[key]:
                raise AutonomyGuardError(f"negative memory context is missing: {key}")
        if not self.do_not_retry_hashes or not all(
            _is_sha256(value) for value in self.do_not_retry_hashes
        ):
            raise AutonomyGuardError("negative memory needs exact do-not-retry hashes")
        if not all(_is_sha256(value) for value in self.orthogonal_context_hashes):
            raise AutonomyGuardError("orthogonal context hashes are invalid")
        if self.strength != "family_refuted" and not self.untested_contexts:
            raise AutonomyGuardError(
                "nonterminal negative memory must preserve important untested contexts"
            )
        if self.strength == "family_refuted":
            orthogonal = len(set(self.orthogonal_context_hashes)) >= 2
            identified = self.identification_impossible and bool(self.identification_receipt_id)
            if not (orthogonal or identified):
                raise AutonomyGuardError(
                    "family refutation requires orthogonal evidence or identification impossibility"
                )
        object.__setattr__(self, "tested_context", MappingProxyType(context))
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(self.evidence_ids)))
        object.__setattr__(
            self,
            "untested_contexts",
            tuple(dict.fromkeys(self.untested_contexts)),
        )
        object.__setattr__(
            self,
            "do_not_retry_hashes",
            tuple(sorted(set(self.do_not_retry_hashes))),
        )
        object.__setattr__(
            self,
            "orthogonal_context_hashes",
            tuple(sorted(set(self.orthogonal_context_hashes))),
        )
        assert_no_scientific_inheritance(self.to_payload())

    def blocks(
        self,
        *,
        family_id: str,
        executable_hashes: Iterable[str],
    ) -> bool:
        if self.strength == "family_refuted" and family_id == self.family_id:
            return True
        return bool(set(executable_hashes) & set(self.do_not_retry_hashes))

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_scoped_negative_memory_v1",
            "hypothesis_id": self.hypothesis_id,
            "family_id": self.family_id,
            "strength": self.strength,
            "evidence_ids": list(self.evidence_ids),
            "tested_context": dict(self.tested_context),
            "untested_contexts": list(self.untested_contexts),
            "do_not_retry_hashes": list(self.do_not_retry_hashes),
            "orthogonal_context_hashes": list(self.orthogonal_context_hashes),
            "identification_impossible": self.identification_impossible,
            "identification_receipt_id": self.identification_receipt_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ScopedNegativeMemory":
        expected_fields = {
            "schema",
            "hypothesis_id",
            "family_id",
            "strength",
            "evidence_ids",
            "tested_context",
            "untested_contexts",
            "do_not_retry_hashes",
            "orthogonal_context_hashes",
            "identification_impossible",
            "identification_receipt_id",
        }
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema")
            != "axiom_rift_v2_scoped_negative_memory_v1"
            or set(payload) != expected_fields
        ):
            raise AutonomyGuardError("negative memory payload schema is invalid")
        list_fields = (
            "evidence_ids",
            "untested_contexts",
            "do_not_retry_hashes",
            "orthogonal_context_hashes",
        )
        if (
            any(not isinstance(payload.get(field), list) for field in list_fields)
            or not isinstance(payload.get("tested_context"), Mapping)
            or not isinstance(payload.get("identification_impossible"), bool)
            or (
                payload.get("identification_receipt_id") is not None
                and not isinstance(payload.get("identification_receipt_id"), str)
            )
        ):
            raise AutonomyGuardError("negative memory payload fields are invalid")
        try:
            return cls(
                hypothesis_id=str(payload["hypothesis_id"]),
                family_id=str(payload["family_id"]),
                strength=str(payload["strength"]),
                evidence_ids=tuple(payload["evidence_ids"]),
                tested_context=dict(payload["tested_context"]),
                untested_contexts=tuple(payload["untested_contexts"]),
                do_not_retry_hashes=tuple(payload["do_not_retry_hashes"]),
                orthogonal_context_hashes=tuple(
                    payload.get("orthogonal_context_hashes", [])
                ),
                identification_impossible=payload["identification_impossible"],
                identification_receipt_id=payload["identification_receipt_id"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AutonomyGuardError(
                f"negative memory payload is invalid: {exc}"
            ) from exc


@dataclass(frozen=True)
class SchedulerProposal:
    hypothesis_id: str
    family_id: str
    dominant_axis: str
    executable_hashes: tuple[str, ...]
    semantic_signature_sha256: str
    expected_information_value: float
    structural_novelty: float
    complementary_potential: float
    scientific_trial_cost: float
    adjacency_penalty: float
    causal_executable: bool
    data_identifiable: bool

    def __post_init__(self) -> None:
        if re.fullmatch(r"V2H[0-9]{4}", self.hypothesis_id) is None:
            raise AutonomyGuardError("scheduler hypothesis identity is invalid")
        _safe_identifier(self.family_id, "family_id")
        _safe_identifier(self.dominant_axis, "dominant_axis")
        if not self.executable_hashes or not all(_is_sha256(v) for v in self.executable_hashes):
            raise AutonomyGuardError("scheduler proposal executable hashes are invalid")
        if not _is_sha256(self.semantic_signature_sha256):
            raise AutonomyGuardError("scheduler semantic signature is invalid")
        for label in (
            "expected_information_value",
            "structural_novelty",
            "complementary_potential",
            "scientific_trial_cost",
            "adjacency_penalty",
        ):
            object.__setattr__(self, label, _bounded_score(getattr(self, label), label))
        object.__setattr__(
            self,
            "executable_hashes",
            tuple(sorted(set(self.executable_hashes))),
        )


@dataclass(frozen=True)
class SchedulerCandidateRecord:
    hypothesis_id: str
    accepted: bool
    rejection_codes: tuple[str, ...]
    priority_score: float | None
    factors: Mapping[str, Any]


@dataclass(frozen=True)
class SchedulerDecision:
    selected_hypothesis_id: str | None
    candidate_records: tuple[SchedulerCandidateRecord, ...]
    decision_sha256: str


@dataclass(frozen=True)
class MissionResearchBudget:
    rolling_window_size: int
    emergency_hypothesis_ceiling: int
    frozen_before_first_h: bool
    result_independent: bool

    def validate_for_open(self) -> None:
        if (
            isinstance(self.rolling_window_size, bool)
            or not isinstance(self.rolling_window_size, int)
            or self.rolling_window_size < 1
        ):
            raise AutonomyGuardError("rolling research window must be positive")
        if (
            isinstance(self.emergency_hypothesis_ceiling, bool)
            or not isinstance(self.emergency_hypothesis_ceiling, int)
            or self.emergency_hypothesis_ceiling <= self.rolling_window_size
        ):
            raise AutonomyGuardError(
                "emergency ceiling must exceed one rolling research window"
            )
        if not self.frozen_before_first_h or not self.result_independent:
            raise AutonomyGuardError(
                "research ceiling must be result-independent and frozen before H"
            )


def choose_next_hypothesis(
    proposals: Iterable[SchedulerProposal],
    research_map: ResearchMap,
    *,
    recent_dominant_axes: tuple[str, ...] = (),
    evaluated_executable_hashes: frozenset[str] = frozenset(),
    seen_semantic_signatures: frozenset[str] = frozenset(),
    negative_memory: tuple[ScopedNegativeMemory, ...] = (),
) -> SchedulerDecision:
    """Return a deterministic recorded choice without inventing a hypothesis."""

    recent = recent_dominant_axes[-RECENT_AXIS_WINDOW:]
    records: list[SchedulerCandidateRecord] = []
    accepted: list[tuple[float, str]] = []
    seen_ids: set[str] = set()
    for proposal in sorted(proposals, key=lambda item: item.hypothesis_id):
        if proposal.hypothesis_id in seen_ids:
            raise AutonomyGuardError("scheduler proposal identities must be unique")
        seen_ids.add(proposal.hypothesis_id)
        coverage = research_map.coverage_deficit(proposal.dominant_axis)
        rejection: list[str] = []
        if not proposal.causal_executable:
            rejection.append("not_causally_executable")
        if not proposal.data_identifiable:
            rejection.append("not_identifiable")
        if proposal.expected_information_value <= 0.0:
            rejection.append("nonpositive_information_value")
        if proposal.semantic_signature_sha256 in seen_semantic_signatures:
            rejection.append("renamed_duplicate")
        if set(proposal.executable_hashes).issubset(evaluated_executable_hashes):
            rejection.append("identical_executable_retry")
        if recent.count(proposal.dominant_axis) >= RECENT_AXIS_MAX:
            rejection.append("dominant_axis_rotation_required")
        if any(
            memory.blocks(
                family_id=proposal.family_id,
                executable_hashes=proposal.executable_hashes,
            )
            for memory in negative_memory
        ):
            rejection.append("scoped_negative_memory_conflict")
        factors = MappingProxyType(
            {
                "expected_information_value": proposal.expected_information_value,
                "coverage_deficit": coverage,
                "structural_novelty": proposal.structural_novelty,
                "complementary_potential": proposal.complementary_potential,
                "scientific_trial_cost": proposal.scientific_trial_cost,
                "adjacency_penalty": proposal.adjacency_penalty,
                "causal_executable": proposal.causal_executable,
                "data_identifiable": proposal.data_identifiable,
            }
        )
        score = None
        if not rejection:
            score = (
                proposal.expected_information_value
                + coverage
                + proposal.structural_novelty
                + proposal.complementary_potential
                - proposal.scientific_trial_cost
                - proposal.adjacency_penalty
            )
            accepted.append((score, proposal.hypothesis_id))
        records.append(
            SchedulerCandidateRecord(
                hypothesis_id=proposal.hypothesis_id,
                accepted=not rejection,
                rejection_codes=tuple(rejection),
                priority_score=score,
                factors=factors,
            )
        )
    selected = sorted(accepted, key=lambda item: (-item[0], item[1]))[0][1] if accepted else None
    payload = {
        "schema": "axiom_rift_v2_scheduler_decision_v1",
        "selected_hypothesis_id": selected,
        "candidate_records": [
            {
                "hypothesis_id": row.hypothesis_id,
                "accepted": row.accepted,
                "rejection_codes": list(row.rejection_codes),
                "priority_score": row.priority_score,
                "factors": dict(row.factors),
            }
            for row in records
        ],
    }
    return SchedulerDecision(
        selected_hypothesis_id=selected,
        candidate_records=tuple(records),
        decision_sha256=sha256_payload(payload),
    )


@dataclass(frozen=True)
class SRouteDecision:
    disposition: str
    current_mode: str
    next_route: str
    scientific_failure: bool


def route_s_disposition(disposition: str, current_mode: str) -> SRouteDecision:
    if disposition not in SCIENTIFIC_DISPOSITIONS:
        raise AutonomyGuardError("unknown Scout disposition")
    if current_mode not in SCOUT_MODES:
        raise AutonomyGuardError("unknown Scout mode")
    if disposition == "broken_execution":
        route, failure = "repair", False
    elif disposition in {"promising", "contextual"}:
        route = "route_to_R" if current_mode in {"s_depth", "s_synthesis"} else "s_depth"
        failure = False
    elif disposition == "complementary":
        route, failure = "preserve_for_synthesis", False
    elif disposition == "unidentified":
        route, failure = "rotate_or_redesign", False
    else:
        route, failure = "close_hypothesis", True
    return SRouteDecision(
        disposition=disposition,
        current_mode=current_mode,
        next_route=route,
        scientific_failure=failure,
    )


def validate_stage_entry(target_stage: str, basis_receipt: Mapping[str, Any]) -> None:
    """Validate synthetic future R/P/M entry evidence without executing a job."""

    if target_stage not in {"R", "P", "M"}:
        raise AutonomyGuardError("stage-entry guard supports only R, P, and M")
    if not isinstance(basis_receipt, Mapping):
        raise AutonomyGuardError("stage-entry basis must be a receipt mapping")
    requirements: dict[str, tuple[tuple[str, Any], ...]] = {
        "R": (
            ("stage", "S"),
            ("outcome", "route_to_R"),
            ("gate_passed", True),
            ("trial_accounting_complete", True),
            ("sizing_mode", "fixed_lot"),
        ),
        "P": (
            ("stage", "R"),
            ("outcome", "research_candidate_confirmed"),
            ("candidate_identity_frozen", True),
            ("trial_accounting_complete", True),
            ("minimum_mt5_confirmation_passed", True),
            ("git_checkpoint_verified", True),
        ),
        "M": (
            ("stage", "P"),
            ("outcome", "selected"),
            ("candidate_identity_frozen", True),
            ("isolated_nine_fold_mt5_passed", True),
            ("sealed_holdout_receipt", True),
            ("sizing_and_risk_frozen", True),
            ("git_checkpoint_verified", True),
        ),
    }
    missing = [
        key
        for key, expected in requirements[target_stage]
        if basis_receipt.get(key) != expected
    ]
    bundle_hash = basis_receipt.get("program_bundle_sha256")
    if not _is_sha256(bundle_hash):
        missing.append("program_bundle_sha256")
    if missing:
        raise AutonomyGuardError(
            f"{target_stage} entry evidence is incomplete: " + ", ".join(sorted(set(missing)))
        )


__all__ = [
    "AutonomyGuardError",
    "GENERIC_DIMENSIONS",
    "HYPOTHESIS_TYPES",
    "HypothesisBatch",
    "MissionResearchBudget",
    "NEGATIVE_STRENGTHS",
    "NumericKnob",
    "RESEARCH_STATES",
    "ResearchAxis",
    "ResearchMap",
    "SCIENTIFIC_DISPOSITIONS",
    "SCOUT_MODES",
    "SRouteDecision",
    "SchedulerCandidateRecord",
    "SchedulerDecision",
    "SchedulerProposal",
    "ScopedNegativeMemory",
    "assert_no_scientific_inheritance",
    "choose_next_hypothesis",
    "route_s_disposition",
    "validate_stage_entry",
]
