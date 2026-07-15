"""Typed evidence-bound decisions for continuing one unchanged Study."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from axiom_rift.core.canonical import CanonicalValue
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.portfolio import QuantTeamDecisionReview


class StudyContinuationError(ValueError):
    """Raised when a Study continuation decision is not fully bound."""


class StudyContinuationOutcome(str, Enum):
    """The only dispositions available after an intermediate Batch."""

    CONTINUE = "continue"
    CLOSE = "close"


class StopRuleState(str, Enum):
    """Evidence-relative state of the exact prior Batch stop rule."""

    REACHED = "reached"
    NOT_REACHED = "not_reached"
    UNRESOLVED = "unresolved"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise StudyContinuationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise StudyContinuationError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _prefixed_digest(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise StudyContinuationError(f"{name} must start with {prefix!r}")
    _digest(name, text.removeprefix(prefix))
    return text


def _sorted_unique_ascii(
    name: str,
    values: object,
    *,
    prefix: str | None = None,
    digest_values: bool = False,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise StudyContinuationError(f"{name} must be a tuple")
    normalized: list[str] = []
    for value in values:
        if prefix is not None:
            normalized.append(_prefixed_digest(name, value, prefix))
        elif digest_values:
            normalized.append(_digest(name, value))
        else:
            normalized.append(_ascii(name, value))
    result = tuple(normalized)
    if result != tuple(sorted(set(result))):
        raise StudyContinuationError(f"{name} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class StudyContinuationDecision:
    """One append-only decision to close or pre-bind the next Study Batch.

    The Writer re-derives every durable binding.  Narrative fields express
    operator judgment but cannot substitute for the exact evidence, Portfolio,
    causal-question, or next-Batch identities.
    """

    study_id: str
    study_hash: str
    question_hash: str
    controlled_chassis_identity: str
    portfolio_snapshot_id: str
    portfolio_axis_id: str
    portfolio_axis_identity: str
    portfolio_decision_id: str
    prior_batch_id: str
    prior_batch_close_record_id: str
    member_executable_ids: tuple[str, ...]
    member_job_ids: tuple[str, ...]
    completion_record_ids: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    stop_rule: str
    stop_rule_state: StopRuleState
    remaining_uncertainty: str
    expected_information_value: str
    other_axis_ids: tuple[str, ...]
    other_axis_opportunity_cost: str
    outcome: StudyContinuationOutcome
    next_batch_id: str | None
    quant_team_review: QuantTeamDecisionReview
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("study_id", self.study_id)
        _digest("study_hash", self.study_hash)
        _digest("question_hash", self.question_hash)
        _prefixed_digest(
            "controlled_chassis_identity",
            self.controlled_chassis_identity,
            "controlled-chassis:",
        )
        _prefixed_digest(
            "portfolio_snapshot_id",
            self.portfolio_snapshot_id,
            "portfolio:",
        )
        _ascii("portfolio_axis_id", self.portfolio_axis_id)
        _prefixed_digest(
            "portfolio_axis_identity",
            self.portfolio_axis_identity,
            "axis:",
        )
        _prefixed_digest(
            "portfolio_decision_id",
            self.portfolio_decision_id,
            "decision:",
        )
        _prefixed_digest("prior_batch_id", self.prior_batch_id, "batch:")
        _digest(
            "prior_batch_close_record_id",
            self.prior_batch_close_record_id,
        )
        _sorted_unique_ascii(
            "member_executable_ids",
            self.member_executable_ids,
            prefix="executable:",
        )
        _sorted_unique_ascii(
            "member_job_ids",
            self.member_job_ids,
            prefix="job:",
        )
        _sorted_unique_ascii(
            "completion_record_ids",
            self.completion_record_ids,
            digest_values=True,
        )
        _sorted_unique_ascii(
            "evidence_hashes",
            self.evidence_hashes,
            digest_values=True,
        )
        if len(self.member_job_ids) != len(self.completion_record_ids):
            raise StudyContinuationError(
                "member Job and completion bindings must have equal cardinality"
            )
        _ascii("stop_rule", self.stop_rule)
        if not isinstance(self.stop_rule_state, StopRuleState):
            raise StudyContinuationError("stop_rule_state must be typed")
        _ascii("remaining_uncertainty", self.remaining_uncertainty)
        _ascii("expected_information_value", self.expected_information_value)
        _sorted_unique_ascii("other_axis_ids", self.other_axis_ids)
        _ascii(
            "other_axis_opportunity_cost",
            self.other_axis_opportunity_cost,
        )
        if not isinstance(self.outcome, StudyContinuationOutcome):
            raise StudyContinuationError("outcome must be typed")
        if not isinstance(self.quant_team_review, QuantTeamDecisionReview):
            raise StudyContinuationError("quant_team_review must be typed")
        chosen_option = (
            "continue-study"
            if self.outcome is StudyContinuationOutcome.CONTINUE
            else "close-study"
        )
        self.quant_team_review.require_options(
            ("close-study", "continue-study"),
            chosen_option_id=chosen_option,
        )
        if self.outcome is StudyContinuationOutcome.CONTINUE:
            if self.stop_rule_state is StopRuleState.REACHED:
                raise StudyContinuationError(
                    "a reached stop rule cannot authorize another Batch"
                )
            if (
                not self.member_executable_ids
                or not self.member_job_ids
                or not self.evidence_hashes
            ):
                raise StudyContinuationError(
                    "Study continuation requires completed evidence-bearing work"
                )
            if self.next_batch_id is None:
                raise StudyContinuationError(
                    "Study continuation must pre-bind the exact next Batch"
                )
            _prefixed_digest("next_batch_id", self.next_batch_id, "batch:")
        elif self.next_batch_id is not None:
            raise StudyContinuationError(
                "Study close cannot pre-bind another Batch"
            )
        object.__setattr__(
            self,
            "identity",
            "study-continuation-decision:"
            + canonical_digest(
                domain="study-continuation-decision",
                payload=self.to_identity_payload(),
            ),
        )

    @property
    def chosen_option_id(self) -> str:
        return (
            "continue-study"
            if self.outcome is StudyContinuationOutcome.CONTINUE
            else "close-study"
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "completion_record_ids": list(self.completion_record_ids),
            "controlled_chassis_identity": self.controlled_chassis_identity,
            "evidence_hashes": list(self.evidence_hashes),
            "expected_information_value": self.expected_information_value,
            "member_executable_ids": list(self.member_executable_ids),
            "member_job_ids": list(self.member_job_ids),
            "next_batch_id": self.next_batch_id,
            "other_axis_ids": list(self.other_axis_ids),
            "other_axis_opportunity_cost": self.other_axis_opportunity_cost,
            "outcome": self.outcome.value,
            "portfolio_axis_id": self.portfolio_axis_id,
            "portfolio_axis_identity": self.portfolio_axis_identity,
            "portfolio_decision_id": self.portfolio_decision_id,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "prior_batch_close_record_id": self.prior_batch_close_record_id,
            "prior_batch_id": self.prior_batch_id,
            "quant_team_review": self.quant_team_review.to_identity_payload(),
            "question_hash": self.question_hash,
            "remaining_uncertainty": self.remaining_uncertainty,
            "schema": "study_continuation_decision.v1",
            "stop_rule": self.stop_rule,
            "stop_rule_state": self.stop_rule_state.value,
            "study_hash": self.study_hash,
            "study_id": self.study_id,
        }


__all__ = [
    "StopRuleState",
    "StudyContinuationDecision",
    "StudyContinuationError",
    "StudyContinuationOutcome",
]
