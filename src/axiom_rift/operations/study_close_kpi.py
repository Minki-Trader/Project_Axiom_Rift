"""Bounded semantic validation for one prospective Study KPI record."""

from __future__ import annotations

from typing import Any, Mapping

from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.study_kpi import StudyKpiProjectionRow


_HEX = frozenset("0123456789abcdef")
_KPI_PAYLOAD_FIELDS = frozenset(
    {
        "completion_record_id",
        "executable_id",
        "executable_display_id",
        "historical_study_close_event_id",
        "historical_study_close_record_id",
        "historical_study_close_revision",
        "metrics",
        "outcome",
        "provenance",
        "sequence",
        "source",
        "study_id",
        "unavailable_reason",
    }
)
_KPI_RECORD_FIELDS = frozenset(
    {
        "event_sequence",
        "event_stream",
        "fingerprint",
        "kind",
        "payload",
        "record_id",
        "status",
        "subject",
    }
)
_KPI_METRICS = frozenset(
    {
        "median_fold_profit_factor_milli",
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
        "net_profit_micropoints",
        "trade_count",
    }
)
_SCIENTIFIC_OUTCOMES = frozenset(
    {"preserved", "supported", "not_supported", "pruned"}
)
_UNAVAILABLE_OUTCOMES = frozenset({"evidence_gap", "not_evaluable"})
_NONPERFORMANCE_OUTCOMES = frozenset(
    {"preserved", "pruned", "evidence_gap", "not_evaluable"}
)


class StudyCloseKpiError(ValueError):
    """One close-time KPI record is malformed or inconsistently bound."""


def _digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and not any(character not in _HEX for character in value)
    )


def validate_prospective_study_kpi(
    event: Mapping[str, Any],
    *,
    historical_kpi_count: int,
    prior_prospective_close_count: int,
) -> None:
    """Validate exactly one close/KPI bundle without reading prior rows."""

    if (
        type(historical_kpi_count) is not int
        or historical_kpi_count < 0
        or type(prior_prospective_close_count) is not int
        or prior_prospective_close_count < 0
    ):
        raise StudyCloseKpiError("Study KPI sequence basis is invalid")
    records = event.get("index_records")
    if not isinstance(records, list):
        raise StudyCloseKpiError("Study close index records are absent")
    kpis = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("kind") == "study-kpi"
    ]
    closes = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("kind") == "study-close"
    ]
    operations = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("kind") == "operation"
    ]
    if len(kpis) != 1 or len(closes) != 1 or len(operations) != 1:
        raise StudyCloseKpiError(
            "Study close requires one operation, close record, and KPI record"
        )
    kpi = kpis[0]
    if set(kpi) != _KPI_RECORD_FIELDS:
        raise StudyCloseKpiError("prospective Study KPI record fields differ")
    payload = kpi.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != _KPI_PAYLOAD_FIELDS:
        raise StudyCloseKpiError("prospective Study KPI payload fields differ")
    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != _KPI_METRICS:
        raise StudyCloseKpiError("prospective Study KPI metrics differ")
    for name, value in metrics.items():
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise StudyCloseKpiError(
                f"prospective Study KPI metric {name} is not typed"
            )
    expected_sequence = (
        historical_kpi_count + prior_prospective_close_count + 1
    )
    sequence = payload.get("sequence")
    study_id = payload.get("study_id")
    outcome = payload.get("outcome")
    if (
        type(sequence) is not int
        or sequence != expected_sequence
        or type(study_id) is not str
        or type(outcome) is not str
        or outcome not in _SCIENTIFIC_OUTCOMES | _UNAVAILABLE_OUTCOMES
        or payload.get("provenance") != "prospective_close"
        or any(
            payload.get(name) is not None
            for name in (
                "historical_study_close_event_id",
                "historical_study_close_record_id",
                "historical_study_close_revision",
            )
        )
        or kpi.get("event_stream") != "study-kpi"
        or kpi.get("event_sequence") != sequence
        or kpi.get("record_id") != study_id
        or kpi.get("subject") != f"Study:{study_id}"
        or kpi.get("status") != outcome
        or kpi.get("fingerprint")
        != canonical_digest(domain="study-kpi", payload=payload)
    ):
        raise StudyCloseKpiError("prospective Study KPI identity differs")
    completion_record_id = payload.get("completion_record_id")
    if completion_record_id is not None and not _digest(completion_record_id):
        raise StudyCloseKpiError(
            "prospective Study KPI completion identity differs"
        )
    unavailable_reason = payload.get("unavailable_reason")
    if unavailable_reason is not None and (
        type(unavailable_reason) is not str
        or not unavailable_reason
        or not unavailable_reason.isascii()
    ):
        raise StudyCloseKpiError(
            "prospective Study KPI unavailable reason differs"
        )
    source = payload.get("source")
    metric_values = tuple(metrics.values())
    if source == "scientific_job_completion":
        source_valid = (
            completion_record_id is not None
            and type(payload.get("executable_id")) is str
            and type(payload.get("executable_display_id")) is str
            and unavailable_reason is None
            and outcome in _SCIENTIFIC_OUTCOMES
        )
    elif source in {
        "validator_derived_source_completion",
        "validator_derived_external_completion",
    }:
        source_valid = (
            completion_record_id is not None
            and unavailable_reason == "non_performance_study"
            and outcome in _NONPERFORMANCE_OUTCOMES
            and all(value is None for value in metric_values)
        )
    elif source == "typed_engineering_failure_completion":
        source_valid = (
            completion_record_id is not None
            and unavailable_reason == "engineering_failure"
            and outcome in _UNAVAILABLE_OUTCOMES
            and all(value is None for value in metric_values)
        )
    elif source == "writer_derived_unavailable":
        source_valid = (
            completion_record_id is None
            and payload.get("executable_id") is None
            and payload.get("executable_display_id") is None
            and unavailable_reason is not None
            and outcome in _UNAVAILABLE_OUTCOMES
            and all(value is None for value in metric_values)
        )
    else:
        source_valid = False
    if not source_valid:
        raise StudyCloseKpiError("prospective Study KPI source binding differs")
    try:
        StudyKpiProjectionRow(
            sequence=sequence,
            closed_at_utc=event["occurred_at_utc"],
            study_id=study_id,
            executable_id=payload.get("executable_id"),
            executable_display_id=payload.get("executable_display_id"),
            net_profit_micropoints=metrics["net_profit_micropoints"],
            median_fold_profit_factor_milli=metrics[
                "median_fold_profit_factor_milli"
            ],
            trade_count=metrics["trade_count"],
            monthly_realized_exit_drawdown_share_of_gross_profit_ppm=metrics[
                "monthly_realized_exit_drawdown_share_of_gross_profit_ppm"
            ],
            outcome=outcome,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StudyCloseKpiError(
            "prospective Study KPI row is not renderable"
        ) from exc
    close = closes[0]
    close_payload = close.get("payload")
    operation_payload = operations[0].get("payload")
    operation_result = (
        operation_payload.get("result")
        if isinstance(operation_payload, Mapping)
        else None
    )
    event_payload = event.get("payload")
    if (
        close.get("subject") != f"Study:{study_id}"
        or close.get("status") != outcome
        or not isinstance(close_payload, Mapping)
        or close_payload.get("study_kpi_record_id") != study_id
        or close_payload.get("outcome") != outcome
        or operations[0].get("record_id") != event.get("operation_id")
        or not isinstance(operation_payload, Mapping)
        or operation_payload.get("event_kind") != "study_closed"
        or not isinstance(operation_result, Mapping)
        or operation_result.get("study_id") != study_id
        or operation_result.get("outcome") != outcome
        or operation_result.get("study_kpi_record_id") != study_id
        or operation_result.get("study_kpi_sequence") != sequence
        or not isinstance(event_payload, Mapping)
        or event_payload.get("outcome") != outcome
        or event_payload.get("kpi_completion_record_id") != completion_record_id
    ):
        raise StudyCloseKpiError(
            "prospective Study close and KPI bindings differ"
        )


__all__ = [
    "StudyCloseKpiError",
    "validate_prospective_study_kpi",
]
