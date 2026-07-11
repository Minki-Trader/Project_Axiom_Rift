"""Validator-bound diagnostic for an underpowered gap selector calibration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    _fold_payloads,
    _selection_method,
)
from axiom_rift.research.gap_recovery_discovery import (
    compute_gap_score,
    executable_configuration_map,
)
from axiom_rift.research.gap_recovery_study import (
    build_environment_manifest,
    build_gap_validation_plan,
    build_measurement,
    build_result_manifest,
    output_names,
)
from axiom_rift.research.trend_study import planned_verdict


MISSION_ID = "MIS-0004"
STUDY_ID = "STU-0044"
CALLABLE_IDENTITY = (
    "axiom_rift.research.gap_recovery_diagnostic.execute_gap_diagnostic.v1"
)
REQUIRED_CALIBRATION_COUNT = 500
SELECTION_TOTAL_EXPOSURES = 424


@dataclass(frozen=True, slots=True)
class GapDiagnosticPacket:
    output_manifest: tuple[tuple[str, str], ...]
    verdict: str

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def _calibration_diagnostic(repository_root: Path) -> dict[str, Any]:
    data = load_observed_development(repository_root)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    folds = _fold_payloads(data)
    rows: list[dict[str, int | str]] = []
    for profile in ("open_gap_30m", "first_bar_response_30m"):
        score, _, _ = compute_gap_score(frame, profile)
        for fold in folds:
            train = fold["train_is"]
            mask = (
                (time >= pd.Timestamp(train["start"]))
                & (time <= pd.Timestamp(train["end"]))
            ).to_numpy()
            count = int((mask & pd.notna(score)).sum())
            rows.append(
                {
                    "fold_id": str(fold["fold_id"]),
                    "observed_calibration_count": count,
                    "profile": profile,
                    "required_calibration_count": REQUIRED_CALIBRATION_COUNT,
                }
            )
    value: dict[str, Any] = {
        "dataset_sha256": DATASET_SHA256,
        "material_identity": OBSERVED_MATERIAL_ID,
        "maximum_observed_calibration_count": max(
            int(row["observed_calibration_count"]) for row in rows
        ),
        "minimum_observed_calibration_count": min(
            int(row["observed_calibration_count"]) for row in rows
        ),
        "required_calibration_count": REQUIRED_CALIBRATION_COUNT,
        "rows": rows,
        "schema": "gap_calibration_diagnostic.v1",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(value)
    return value


def _metrics() -> dict[str, int]:
    names = (
        "append_invariance_mismatch_count",
        "causality_violation_count",
        "daily_entries_max_milli",
        "daily_entries_median_milli",
        "daily_entries_p10_milli",
        "daily_entries_p90_milli",
        "eligible_day_count",
        "entries_per_day_milli",
        "evaluable_folds",
        "feature_control_worst_delta_net_profit_micropoints",
        "gap_excluded_signal_count",
        "median_fold_profit_factor_milli",
        "monthly_realized_exit_drawdown_micropoints",
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
        "net_profit_micropoints",
        "opposite_sign_worst_delta_net_profit_micropoints",
        "positive_regime_count",
        "prefix_invariance_mismatch_count",
        "stress_net_profit_micropoints",
        "supported_positive_regime_count",
        "top5_profit_day_share_ppm",
        "trade_count",
        "unknown_cost_unresolved_signal_count",
        "winning_fold_count",
        "zero_entry_day_rate_ppm",
    )
    result = {name: 0 for name in names}
    result.update(
        {
            "feature_control_worst_pvalue_upper_ppm": 1_000_000,
            "nonfinite_metric_count": 1,
            "opposite_sign_pvalue_upper_ppm": 1_000_000,
            "selection_aware_pvalue_ppm": 1_000_000,
        }
    )
    return result


def _evaluation(
    *,
    execution: RunningJobExecution,
    executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    configurations = executable_configuration_map()
    metrics = _metrics()
    value: dict[str, Any] = {
        "claim_limits": [
            "calibration_count_below_preregistered_minimum",
            "no_performance_or_directional_claim",
        ],
        "direction_metrics": [
            {"direction": direction, "net_profit_micropoints": 0, "trade_count": 0}
            for direction in ("long", "short")
        ],
        "evaluable": False,
        "fold_metrics": [
            {
                "fold_id": f"rw_{index:03d}",
                "net_profit_micropoints": 0,
                "profit_factor_milli": 0,
                "stress_net_profit_micropoints": 0,
                "trade_count": 0,
                "unresolved_cost_signal_count": 0,
            }
            for index in range(1, 10)
        ],
        "job_execution": {**execution.payload(), "identity": execution.identity},
        "metrics": metrics,
        "regime_metrics": [
            {
                "evaluable_fold_count": 0,
                "net_profit_micropoints": 0,
                "regime": regime,
                "trade_count": 0,
                "winning_fold_count": 0,
            }
            for regime in ("low", "middle", "high")
        ],
        "schema": "gap_recovery_evaluation.v1",
        "selection_context": [
            {
                "configuration_id": configuration.configuration_id,
                "executable_id": identity,
                "net_profit_micropoints": 0,
                "selection_aware_pvalue_ppm": 1_000_000,
            }
            for identity, configuration in configurations.items()
        ],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_metrics": [
            {"net_profit_micropoints": 0, "session": session, "trade_count": 0}
            for session in (
                "broker_01_07",
                "broker_08_14",
                "broker_15_22",
                "broker_23_00",
            )
        ],
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "subject_configuration_id": configurations[executable_id].configuration_id,
        "subject_executable_id": executable_id,
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(value)
    return value


def execute_gap_diagnostic(
    *, repository_root: str | Path, execution: RunningJobExecution
) -> GapDiagnosticPacket:
    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(
        execution, expected_callable_identity=CALLABLE_IDENTITY
    )
    spec = binding["spec"]
    subject = spec.get("evidence_subject")
    configurations = executable_configuration_map()
    if (
        binding.get("mission_id") != MISSION_ID
        or binding.get("study_id") != STUDY_ID
        or not isinstance(subject, dict)
        or subject.get("id") not in configurations
    ):
        raise ValueError("diagnostic Job binding is invalid")
    executable_id = subject["id"]
    plan = build_gap_validation_plan(executable_id)
    names = output_names(executable_id)
    diagnostic = _calibration_diagnostic(root)
    diagnostic_hash = writer.evidence.finalize(canonical_bytes(diagnostic)).sha256
    manifest = {
        "diagnostic_artifact_hash": diagnostic_hash,
        "schema": "gap_calibration_diagnostic_manifest.v1",
    }
    manifest_hash = writer.evidence.finalize(canonical_bytes(manifest)).sha256
    evaluation = _evaluation(
        execution=execution,
        executable_id=executable_id,
        surface_artifact_hash=diagnostic_hash,
        surface_manifest_hash=manifest_hash,
    )
    evaluation_hash = writer.evidence.finalize(canonical_bytes(evaluation)).sha256
    measurement = build_measurement(
        executable_id=executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        evaluation_artifact_hash=evaluation_hash,
        evaluation=evaluation,
    )
    measurement_hash = writer.evidence.finalize(canonical_bytes(measurement)).sha256
    result = build_result_manifest(
        executable_id=executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_artifact_hash=measurement_hash,
    )
    outputs = {
        names["context"]: evaluation_hash,
        names["environment"]: writer.evidence.finalize(
            canonical_bytes(build_environment_manifest())
        ).sha256,
        names["measurement"]: measurement_hash,
        names["plan"]: writer.evidence.finalize(canonical_bytes(plan)).sha256,
        names["result"]: writer.evidence.finalize(canonical_bytes(result)).sha256,
    }
    if set(outputs) != set(spec["expected_outputs"]):
        raise ValueError("diagnostic outputs differ from the Job declaration")
    verdict = planned_verdict(plan, measurement)
    if verdict != "not_evaluable":
        raise ValueError("calibration diagnostic must remain not evaluable")
    return GapDiagnosticPacket(tuple(sorted(outputs.items())), verdict)


__all__ = ["CALLABLE_IDENTITY", "GapDiagnosticPacket", "execute_gap_diagnostic"]
