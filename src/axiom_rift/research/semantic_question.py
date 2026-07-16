"""Exact declared-question identity and explicit scientific-work lineage.

This module does not infer natural-language equivalence or heuristically strip
controlled-variable text.  Exact question cores are deterministic;
equivalence between distinct cores requires an explicit typed proposal with
durable review records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from axiom_rift.core.canonical import CanonicalValue
from axiom_rift.core.identity import canonical_digest


SEMANTIC_QUESTION_CORE_SCHEMA = "semantic_question_core.v1"
SEMANTIC_QUESTION_EQUIVALENCE_SCHEMA = (
    "semantic_question_equivalence_proposal.v1"
)
SEMANTIC_QUESTION_LINEAGE_SCHEMA = "semantic_question_lineage_proposal.v1"
SEMANTIC_QUESTION_STUDY_BINDING_SCHEMA = (
    "semantic_question_study_binding.v1"
)

_ASCII_WHITESPACE = frozenset(" \t\n\r\v\f")


class SemanticQuestionError(ValueError):
    """A semantic question identity, equivalence, or lineage is malformed."""


class SemanticQuestionRelation(str, Enum):
    """Typed relation between predecessor and successor scientific work."""

    ENGINEERING_REENTRY = "engineering_reentry"
    CONTINUATION = "continuation"
    INDEPENDENT_REPLICATION = "independent_replication"
    CONFIRMATION = "confirmation"
    SEMANTIC_REVISION = "semantic_revision"


def canonicalize_causal_question(value: object) -> str:
    """Collapse ASCII whitespace without interpreting question semantics."""

    if type(value) is not str:
        raise SemanticQuestionError("causal_question must be str")
    if not value or not value.isascii():
        raise SemanticQuestionError("causal_question must be non-empty ASCII")
    if any(
        (ord(character) < 32 and character not in _ASCII_WHITESPACE)
        or ord(character) == 127
        for character in value
    ):
        raise SemanticQuestionError(
            "causal_question contains a non-whitespace ASCII control"
        )
    normalized = " ".join(value.split())
    if not normalized:
        raise SemanticQuestionError("causal_question must contain visible text")
    return normalized


def _canonical_ascii_text(name: str, value: object) -> str:
    if type(value) is not str:
        raise SemanticQuestionError(f"{name} must be str")
    if not value or not value.isascii():
        raise SemanticQuestionError(f"{name} must be non-empty ASCII")
    if any(
        (ord(character) < 32 and character not in _ASCII_WHITESPACE)
        or ord(character) == 127
        for character in value
    ):
        raise SemanticQuestionError(f"{name} contains an ASCII control")
    normalized = " ".join(value.split())
    if not normalized:
        raise SemanticQuestionError(f"{name} must contain visible text")
    return normalized


def _canonical_variable(name: str, value: object) -> str:
    normalized = _canonical_ascii_text(name, value)
    if normalized != value:
        raise SemanticQuestionError(f"{name} must use canonical ASCII whitespace")
    return normalized


def _variables(name: str, value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise SemanticQuestionError(f"{name} must be a non-empty tuple[str, ...]")
    normalized = tuple(
        _canonical_variable(f"{name}[{index}]", item)
        for index, item in enumerate(value)
    )
    if len(normalized) != len(set(normalized)):
        raise SemanticQuestionError(f"{name} must not contain duplicates")
    return tuple(sorted(normalized))


def _question_variables(name: str, value: object) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise SemanticQuestionError(f"question {name} must be a list or tuple")
    return tuple(value)


def _prefixed_digest(name: str, value: object, *, prefix: str) -> str:
    text = _canonical_variable(name, value)
    if not text.startswith(prefix):
        raise SemanticQuestionError(f"{name} must use {prefix}<sha256>")
    digest = text.removeprefix(prefix)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise SemanticQuestionError(f"{name} must contain a lowercase SHA-256")
    return text


def _study_id(name: str, value: object) -> str:
    text = _canonical_variable(name, value)
    suffix = text.removeprefix("STU-")
    allowed = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
    if (
        not text.startswith("STU-")
        or not suffix
        or suffix[0] == "-"
        or suffix[-1] == "-"
        or any(character not in allowed for character in suffix)
    ):
        raise SemanticQuestionError(f"{name} is not a canonical Study id")
    return text


def semantic_question_study_binding_id(
    *,
    semantic_question_core_id: str,
    study_id: str,
) -> str:
    core_id = _prefixed_digest(
        "semantic_question_core_id",
        semantic_question_core_id,
        prefix="semantic-question-core:",
    )
    canonical_study_id = _study_id("study_id", study_id)
    # One Study may bind exactly one declared question core.  The core is
    # validated here and stored as the record fingerprint, but is deliberately
    # excluded from the primary key so a second core collides instead of
    # silently creating another binding for the same Study.
    return f"semantic-question-study:{canonical_study_id}"


def _record_ids(name: str, value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise SemanticQuestionError(f"{name} must be a non-empty tuple[str, ...]")
    normalized = tuple(
        _canonical_variable(f"{name}[{index}]", item)
        for index, item in enumerate(value)
    )
    if len(normalized) != len(set(normalized)):
        raise SemanticQuestionError(f"{name} must not contain duplicates")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticQuestionCore:
    """One exact declaration excluding outer evaluation-protocol fields."""

    causal_question: str
    changed_variables: tuple[str, ...]
    controlled_variables: tuple[str, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        causal_question = canonicalize_causal_question(self.causal_question)
        changed_variables = _variables(
            "changed_variables", self.changed_variables
        )
        controlled_variables = _variables(
            "controlled_variables", self.controlled_variables
        )
        overlap = set(changed_variables).intersection(controlled_variables)
        if overlap:
            raise SemanticQuestionError(
                "changed_variables and controlled_variables must be disjoint"
            )
        object.__setattr__(self, "causal_question", causal_question)
        object.__setattr__(self, "changed_variables", changed_variables)
        object.__setattr__(self, "controlled_variables", controlled_variables)
        object.__setattr__(
            self,
            "identity",
            "semantic-question-core:"
            + canonical_digest(
                domain="semantic-question-core",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "causal_question": self.causal_question,
            "changed_variables": list(self.changed_variables),
            "controlled_variables": list(self.controlled_variables),
            "schema": SEMANTIC_QUESTION_CORE_SCHEMA,
        }

    @classmethod
    def from_question_manifest(
        cls, question: Mapping[str, object]
    ) -> SemanticQuestionCore:
        """Derive only the semantic fields from a full Study question."""

        if not isinstance(question, Mapping):
            raise SemanticQuestionError("question must be a mapping")
        required = {
            "causal_question",
            "changed_variables",
            "controlled_variables",
        }
        if not required.issubset(question):
            raise SemanticQuestionError("question lacks semantic core fields")
        return cls(
            causal_question=question["causal_question"],  # type: ignore[arg-type]
            changed_variables=_question_variables(
                "changed_variables", question["changed_variables"]
            ),
            controlled_variables=_question_variables(
                "controlled_variables", question["controlled_variables"]
            ),
        )

    @classmethod
    def from_identity_payload(
        cls, value: Mapping[str, object]
    ) -> SemanticQuestionCore:
        fields = {
            "causal_question",
            "changed_variables",
            "controlled_variables",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise SemanticQuestionError(
                "semantic question core payload is malformed"
            )
        if value.get("schema") != SEMANTIC_QUESTION_CORE_SCHEMA:
            raise SemanticQuestionError(
                "semantic question core schema is unsupported"
            )
        core = cls.from_question_manifest(value)
        if core.to_identity_payload() != dict(value):
            raise SemanticQuestionError(
                "semantic question core payload is not canonical"
            )
        return core


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticQuestionEquivalenceProposal:
    """Explicit core reconciliation, separate from scientific-work lineage."""

    canonical_study_id: str
    equivalent_study_id: str
    canonical_core_id: str
    equivalent_core_id: str
    rationale: str
    basis_record_ids: tuple[str, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        canonical_study_id = _study_id(
            "canonical_study_id",
            self.canonical_study_id,
        )
        equivalent_study_id = _study_id(
            "equivalent_study_id",
            self.equivalent_study_id,
        )
        if canonical_study_id == equivalent_study_id:
            raise SemanticQuestionError(
                "equivalence proposal requires two distinct Studies"
            )
        canonical_core_id = _prefixed_digest(
            "canonical_core_id",
            self.canonical_core_id,
            prefix="semantic-question-core:",
        )
        equivalent_core_id = _prefixed_digest(
            "equivalent_core_id",
            self.equivalent_core_id,
            prefix="semantic-question-core:",
        )
        if canonical_core_id == equivalent_core_id:
            raise SemanticQuestionError(
                "equivalence proposal requires two distinct exact cores"
            )
        rationale = _canonical_ascii_text("rationale", self.rationale)
        basis_record_ids = _record_ids(
            "basis_record_ids", self.basis_record_ids
        )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "basis_record_ids", basis_record_ids)
        object.__setattr__(
            self,
            "identity",
            "semantic-question-equivalence:"
            + canonical_digest(
                domain="semantic-question-equivalence-proposal",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "basis_record_ids": list(self.basis_record_ids),
            "canonical_core_id": self.canonical_core_id,
            "canonical_study_id": self.canonical_study_id,
            "equivalent_core_id": self.equivalent_core_id,
            "equivalent_study_id": self.equivalent_study_id,
            "rationale": self.rationale,
            "schema": SEMANTIC_QUESTION_EQUIVALENCE_SCHEMA,
        }

    @classmethod
    def from_identity_payload(
        cls, value: Mapping[str, object]
    ) -> SemanticQuestionEquivalenceProposal:
        fields = {
            "basis_record_ids",
            "canonical_core_id",
            "canonical_study_id",
            "equivalent_core_id",
            "equivalent_study_id",
            "rationale",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise SemanticQuestionError(
                "semantic question equivalence payload is malformed"
            )
        if value.get("schema") != SEMANTIC_QUESTION_EQUIVALENCE_SCHEMA:
            raise SemanticQuestionError(
                "semantic question equivalence schema is unsupported"
            )
        basis_record_ids = value.get("basis_record_ids")
        if type(basis_record_ids) is not list:
            raise SemanticQuestionError(
                "equivalence basis_record_ids must be a canonical list"
            )
        proposal = cls(
            canonical_study_id=value["canonical_study_id"],  # type: ignore[arg-type]
            equivalent_study_id=value["equivalent_study_id"],  # type: ignore[arg-type]
            canonical_core_id=value["canonical_core_id"],  # type: ignore[arg-type]
            equivalent_core_id=value["equivalent_core_id"],  # type: ignore[arg-type]
            rationale=value["rationale"],  # type: ignore[arg-type]
            basis_record_ids=tuple(basis_record_ids),
        )
        if proposal.to_identity_payload() != dict(value):
            raise SemanticQuestionError(
                "semantic question equivalence payload is not canonical"
            )
        return proposal


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticQuestionLineageProposal:
    """Typed relation between work items without manufacturing equivalence."""

    predecessor_study_id: str
    successor_study_id: str
    predecessor_core_id: str
    successor_core_id: str
    relation: SemanticQuestionRelation
    rationale: str
    basis_record_ids: tuple[str, ...]
    equivalence_proposal_id: str | None = None
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        predecessor_study_id = _study_id(
            "predecessor_study_id",
            self.predecessor_study_id,
        )
        successor_study_id = _study_id(
            "successor_study_id",
            self.successor_study_id,
        )
        if predecessor_study_id == successor_study_id:
            raise SemanticQuestionError(
                "semantic question lineage requires two distinct Studies"
            )
        predecessor_core_id = _prefixed_digest(
            "predecessor_core_id",
            self.predecessor_core_id,
            prefix="semantic-question-core:",
        )
        successor_core_id = _prefixed_digest(
            "successor_core_id",
            self.successor_core_id,
            prefix="semantic-question-core:",
        )
        if not isinstance(self.relation, SemanticQuestionRelation):
            raise SemanticQuestionError(
                "relation must be a SemanticQuestionRelation"
            )
        equivalence_proposal_id = self.equivalence_proposal_id
        if equivalence_proposal_id is not None:
            equivalence_proposal_id = _prefixed_digest(
                "equivalence_proposal_id",
                equivalence_proposal_id,
                prefix="semantic-question-equivalence:",
            )
        same_core = predecessor_core_id == successor_core_id
        if self.relation is SemanticQuestionRelation.SEMANTIC_REVISION:
            if same_core or equivalence_proposal_id is not None:
                raise SemanticQuestionError(
                    "semantic_revision requires distinct non-equivalent cores"
                )
        elif same_core:
            if equivalence_proposal_id is not None:
                raise SemanticQuestionError(
                    "same-core lineage must not cite redundant equivalence"
                )
        elif equivalence_proposal_id is None:
            raise SemanticQuestionError(
                "different-core lineage requires explicit equivalence"
            )
        rationale = _canonical_ascii_text("rationale", self.rationale)
        basis_record_ids = _record_ids(
            "basis_record_ids", self.basis_record_ids
        )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "basis_record_ids", basis_record_ids)
        object.__setattr__(
            self,
            "equivalence_proposal_id",
            equivalence_proposal_id,
        )
        object.__setattr__(
            self,
            "identity",
            "semantic-question-lineage:"
            + canonical_digest(
                domain="semantic-question-lineage-proposal",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "basis_record_ids": list(self.basis_record_ids),
            "equivalence_proposal_id": self.equivalence_proposal_id,
            "predecessor_core_id": self.predecessor_core_id,
            "predecessor_study_id": self.predecessor_study_id,
            "rationale": self.rationale,
            "relation": self.relation.value,
            "schema": SEMANTIC_QUESTION_LINEAGE_SCHEMA,
            "successor_core_id": self.successor_core_id,
            "successor_study_id": self.successor_study_id,
        }

    @classmethod
    def from_identity_payload(
        cls, value: Mapping[str, object]
    ) -> SemanticQuestionLineageProposal:
        fields = {
            "basis_record_ids",
            "equivalence_proposal_id",
            "predecessor_core_id",
            "predecessor_study_id",
            "rationale",
            "relation",
            "schema",
            "successor_core_id",
            "successor_study_id",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise SemanticQuestionError(
                "semantic question lineage payload is malformed"
            )
        if value.get("schema") != SEMANTIC_QUESTION_LINEAGE_SCHEMA:
            raise SemanticQuestionError(
                "semantic question lineage schema is unsupported"
            )
        basis_record_ids = value.get("basis_record_ids")
        if type(basis_record_ids) is not list:
            raise SemanticQuestionError(
                "lineage basis_record_ids must be a canonical list"
            )
        try:
            relation = SemanticQuestionRelation(value.get("relation"))
        except (TypeError, ValueError) as exc:
            raise SemanticQuestionError(
                "semantic question lineage relation is invalid"
            ) from exc
        proposal = cls(
            predecessor_study_id=value["predecessor_study_id"],  # type: ignore[arg-type]
            successor_study_id=value["successor_study_id"],  # type: ignore[arg-type]
            predecessor_core_id=value["predecessor_core_id"],  # type: ignore[arg-type]
            successor_core_id=value["successor_core_id"],  # type: ignore[arg-type]
            relation=relation,
            rationale=value["rationale"],  # type: ignore[arg-type]
            basis_record_ids=tuple(basis_record_ids),
            equivalence_proposal_id=value["equivalence_proposal_id"],  # type: ignore[arg-type]
        )
        if proposal.to_identity_payload() != dict(value):
            raise SemanticQuestionError(
                "semantic question lineage payload is not canonical"
            )
        return proposal


__all__ = [
    "SEMANTIC_QUESTION_CORE_SCHEMA",
    "SEMANTIC_QUESTION_EQUIVALENCE_SCHEMA",
    "SEMANTIC_QUESTION_LINEAGE_SCHEMA",
    "SEMANTIC_QUESTION_STUDY_BINDING_SCHEMA",
    "SemanticQuestionCore",
    "SemanticQuestionEquivalenceProposal",
    "SemanticQuestionError",
    "SemanticQuestionLineageProposal",
    "SemanticQuestionRelation",
    "canonicalize_causal_question",
    "semantic_question_study_binding_id",
]
