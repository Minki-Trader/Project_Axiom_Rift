"""Small shared types and keyed joins for historical cost semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from axiom_rift.research.historical_cost_semantics import (
    HistoricalAuthorityCursor,
    HistoricalCostInterpretation,
    HistoricalCostQualificationState,
    HistoricalCostSemanticCriterion,
    HistoricalCostSemanticsError,
    HistoricalSpreadSemanticClass,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


LATCH_STREAM = "historical-cost-semantics:completed-period-spread"
LATCH_RECORD_KIND = "historical-cost-semantics-latch"
LATCH_EVENT_KIND = "historical_cost_semantics_latch_recorded"
COMPLETION_SCOPE_RECORD_KIND = "historical-cost-semantics-completion"
COMPLETION_SCOPE_SCHEMA = "historical_cost_semantics_completion.v1"


class HistoricalCostSemanticsProjectionError(RuntimeError):
    """A shared completion join or semantic binding is malformed."""


@dataclass(frozen=True, slots=True, order=True)
class HistoricalCriterionBinding:
    criterion_id: str
    metric: str


@dataclass(frozen=True, slots=True)
class HistoricalCostQualification:
    completion_record_id: str
    semantic_class: HistoricalSpreadSemanticClass
    interpretation: HistoricalCostInterpretation
    state: HistoricalCostQualificationState
    reason: str
    proxy_only: bool


def preserved_independent_scopes(
    semantic_class: HistoricalSpreadSemanticClass,
) -> tuple[str, ...]:
    return {
        HistoricalSpreadSemanticClass.EXECUTION_COST_MEASUREMENT_ONLY: (
            "feature_causality",
            "gross_mechanism",
        ),
        HistoricalSpreadSemanticClass.COMPLETED_PERIOD_PROXY_FEATURE: (
            "completed_period_spread_feature_causality",
            "gross_mechanism",
        ),
        HistoricalSpreadSemanticClass.NATIVE_COST_OUTCOME_LABEL_ONLY: (
            "feature_causality",
            "gross_mechanism",
            "score_and_selector_path",
        ),
        HistoricalSpreadSemanticClass.DECISION_SURFACE_COST_DEPENDENT: (),
        HistoricalSpreadSemanticClass.CAUSAL_POLICY_COST_STATE_DEPENDENT: (),
        HistoricalSpreadSemanticClass.ENGINEERING: (),
    }[semantic_class]


def normalized_criterion(
    criterion: HistoricalCostSemanticCriterion | str,
    bindings: tuple[HistoricalCriterionBinding, ...],
) -> HistoricalCostSemanticCriterion | None:
    if isinstance(criterion, HistoricalCostSemanticCriterion):
        return criterion
    if type(criterion) is not str or not criterion or not criterion.isascii():
        raise HistoricalCostSemanticsProjectionError(
            "criterion must be a typed semantic criterion or bound ASCII id"
        )
    matches = [item for item in bindings if item.criterion_id == criterion]
    if len(matches) != 1:
        raise HistoricalCostSemanticsProjectionError(
            "criterion is not uniquely bound to the frozen completion"
        )
    by_metric = {
        "net_profit_micropoints": (
            HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST
        ),
        "stress_net_profit_micropoints": (
            HistoricalCostSemanticCriterion.C02_STRESS_RESILIENCE
        ),
        "causality_violation_count": (
            HistoricalCostSemanticCriterion.C03_DECISION_TIME_CAUSALITY
        ),
        "unknown_cost_unresolved_signal_count": (
            HistoricalCostSemanticCriterion.C04_UNKNOWN_COST_RESOLUTION
        ),
        "median_fold_profit_factor_milli": (
            HistoricalCostSemanticCriterion.C05_FIXED_LOT_PROFIT_FACTOR
        ),
    }
    if matches[0].metric in by_metric:
        return by_metric[matches[0].metric]
    return {
        "B01-positive-native-cost": (
            HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST
        ),
        "B02-fold-profit-factor": (
            HistoricalCostSemanticCriterion.C05_FIXED_LOT_PROFIT_FACTOR
        ),
        "B03-slippage-stress": (
            HistoricalCostSemanticCriterion.C02_STRESS_RESILIENCE
        ),
        "C03-decision-time-causality": (
            HistoricalCostSemanticCriterion.C03_DECISION_TIME_CAUSALITY
        ),
        "C04-resolved-cost": (
            HistoricalCostSemanticCriterion.C04_UNKNOWN_COST_RESOLUTION
        ),
    }.get(criterion)


def record_cursor(record: IndexRecord) -> HistoricalAuthorityCursor:
    try:
        return HistoricalAuthorityCursor(
            sequence=record.authority_sequence,  # type: ignore[arg-type]
            event_id=record.authority_event_id,  # type: ignore[arg-type]
            offset=record.authority_offset,  # type: ignore[arg-type]
        )
    except HistoricalCostSemanticsError as exc:
        raise HistoricalCostSemanticsProjectionError(
            "historical spread record lacks authenticated Journal authority"
        ) from exc


def at_or_before(
    record: IndexRecord,
    upper: HistoricalAuthorityCursor,
) -> bool:
    cursor = record_cursor(record)
    if cursor.sequence < upper.sequence:
        return True
    if cursor.sequence > upper.sequence:
        return False
    if cursor.event_id != upper.event_id or cursor.offset != upper.offset:
        raise HistoricalCostSemanticsProjectionError(
            "record shares the audit sequence but not its exact authority event"
        )
    return True


def _subject_executable(
    declaration: IndexRecord,
) -> tuple[str, Mapping[str, Any]]:
    spec = declaration.payload.get("spec")
    subject = None if not isinstance(spec, Mapping) else spec.get(
        "evidence_subject"
    )
    if (
        not isinstance(spec, Mapping)
        or not isinstance(subject, Mapping)
        or subject.get("kind") != "Executable"
        or type(subject.get("id")) is not str
        or not subject["id"].startswith("executable:")
    ):
        raise HistoricalCostSemanticsProjectionError(
            "completion Job declaration lacks an exact Executable evidence subject"
        )
    return subject["id"], spec


def completion_join(
    index: LocalIndex | LocalIndexView,
    completion: IndexRecord,
    upper: HistoricalAuthorityCursor,
) -> tuple[IndexRecord, IndexRecord, str, Mapping[str, Any], str]:
    job_id = completion.payload.get("job_id")
    if type(job_id) is not str or not job_id.startswith("job:"):
        raise HistoricalCostSemanticsProjectionError(
            "completion lacks its exact Job id"
        )
    declaration = index.get("job-declared", job_id)
    if declaration is None or not at_or_before(declaration, upper):
        raise HistoricalCostSemanticsProjectionError(
            "completion lost its pre-boundary Job declaration"
        )
    executable_id, _spec = _subject_executable(declaration)
    trial = index.get("trial", executable_id)
    executable = None if trial is None else trial.payload.get("executable")
    cost_contract = (
        None
        if not isinstance(executable, Mapping)
        else executable.get("cost_contract")
    )
    if (
        trial is None
        or not at_or_before(trial, upper)
        or not isinstance(executable, Mapping)
        or type(cost_contract) is not str
        or not cost_contract.startswith("cost:")
        or type(declaration.payload.get("study_id")) is not str
        or type(trial.payload.get("study_id")) is not str
    ):
        raise HistoricalCostSemanticsProjectionError(
            "completion lost its exact pre-boundary Executable trial"
        )
    scientific = completion.payload.get("scientific")
    if isinstance(scientific, Mapping) and scientific.get(
        "executable_id"
    ) not in {None, executable_id}:
        raise HistoricalCostSemanticsProjectionError(
            "completion scientific subject differs from its Job declaration"
        )
    return declaration, trial, executable_id, executable, cost_contract


def is_spread_cost_contract(cost_contract: str) -> bool:
    return cost_contract.startswith("cost:") and "spread" in cost_contract.casefold()


def completion_claims(
    scientific: Mapping[str, Any],
    declaration: IndexRecord,
) -> tuple[str, ...]:
    values: set[str] = set()
    direct = scientific.get("claims")
    if isinstance(direct, list):
        for item in direct:
            claim_id = (
                item
                if type(item) is str
                else item.get("claim_id")
                if isinstance(item, Mapping)
                else None
            )
            if type(claim_id) is not str or not claim_id.isascii():
                raise HistoricalCostSemanticsProjectionError(
                    "completion scientific claims are malformed"
                )
            values.add(claim_id)
    spec = declaration.payload.get("spec")
    binding = None if not isinstance(spec, Mapping) else spec.get(
        "scientific_binding"
    )
    planned = None if not isinstance(binding, Mapping) else binding.get(
        "planned_claims"
    )
    if isinstance(planned, list):
        for item in planned:
            if type(item) is not str or not item.isascii():
                raise HistoricalCostSemanticsProjectionError(
                    "Job planned claims are malformed"
                )
            values.add(item)
    if not values:
        raise HistoricalCostSemanticsProjectionError(
            "scientific spread completion has no exact claim inventory"
        )
    return tuple(sorted(values))


def adjudication_claims_and_criteria(
    value: object,
) -> tuple[tuple[str, ...], tuple[HistoricalCriterionBinding, ...]]:
    if not isinstance(value, Mapping):
        return (), ()
    claims_raw = value.get("claims")
    criteria_raw = value.get("criteria")
    claims: set[str] = set()
    criteria: list[HistoricalCriterionBinding] = []
    if isinstance(claims_raw, list):
        for item in claims_raw:
            claim_id = None if not isinstance(item, Mapping) else item.get(
                "claim_id"
            )
            if type(claim_id) is not str or not claim_id.isascii():
                raise HistoricalCostSemanticsProjectionError(
                    "historical adjudication claim is malformed"
                )
            claims.add(claim_id)
    if isinstance(criteria_raw, list):
        for item in criteria_raw:
            criterion_id = (
                None if not isinstance(item, Mapping) else item.get("criterion_id")
            )
            metric = None if not isinstance(item, Mapping) else item.get("metric")
            if (
                type(criterion_id) is not str
                or not criterion_id.isascii()
                or type(metric) is not str
                or not metric.isascii()
            ):
                raise HistoricalCostSemanticsProjectionError(
                    "historical adjudication criterion is malformed"
                )
            criteria.append(HistoricalCriterionBinding(criterion_id, metric))
    normalized = tuple(sorted(criteria))
    if len({item.criterion_id for item in normalized}) != len(normalized):
        raise HistoricalCostSemanticsProjectionError(
            "historical adjudication criteria are not unique"
        )
    return tuple(sorted(claims)), normalized


def class_for_study(
    study_id: str,
    *,
    scientific: bool,
    rules: Mapping[HistoricalSpreadSemanticClass, tuple[str, ...]],
) -> HistoricalSpreadSemanticClass:
    if not scientific:
        return HistoricalSpreadSemanticClass.ENGINEERING
    matches = [
        semantic_class
        for semantic_class, studies in rules.items()
        if study_id in studies
    ]
    if len(matches) > 1:
        raise HistoricalCostSemanticsProjectionError(
            "Study matches more than one spread semantic class"
        )
    return (
        matches[0]
        if matches
        else HistoricalSpreadSemanticClass.EXECUTION_COST_MEASUREMENT_ONLY
    )


__all__ = [
    "COMPLETION_SCOPE_RECORD_KIND",
    "COMPLETION_SCOPE_SCHEMA",
    "HistoricalCostQualification",
    "HistoricalCostSemanticsProjectionError",
    "HistoricalCriterionBinding",
    "LATCH_EVENT_KIND",
    "LATCH_RECORD_KIND",
    "LATCH_STREAM",
    "adjudication_claims_and_criteria",
    "at_or_before",
    "class_for_study",
    "completion_claims",
    "completion_join",
    "is_spread_cost_contract",
    "normalized_criterion",
    "preserved_independent_scopes",
    "record_cursor",
]
