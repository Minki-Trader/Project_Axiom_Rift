"""Discovery runner for registered US100-US500 downside spillover Study."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.operations import writer as writer_module
from axiom_rift.research import validation as scientific_validator_module
from axiom_rift.research.cross_asset_downside_spillover_discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_TOTAL_EXPOSURES,
    _compute_registered_cross_asset_downside_spillover_surface,
    cross_asset_downside_spillover_implementation_sha256,
    cross_asset_downside_spillover_executable_configuration_map,
    loader_implementation_sha256,
    project_cross_asset_downside_spillover_evaluation,
    trend_dependency_sha256,
    us500_raw_sha256,
    us500_source_implementation_sha256,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    SCIENTIFIC_MEASUREMENT_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    build_validation_plan,
)
from axiom_rift.research.us500_source import us500_source_contract
from axiom_rift.research.us500_source_study import (
    source_dependency_sha256,
    source_study_implementation_sha256,
    source_validator_implementation_sha256,
)


MISSION_ID = "MIS-0001"
STUDY_ID = "STU-0021"
CALLABLE_IDENTITY = "axiom_rift.research.cross_asset_downside_spillover_study.execute_cross_asset_downside_spillover_job.v1"
SURFACE_SCHEMA = "cross_asset_downside_spillover_surface.v1"
EVALUATION_SCHEMA = "cross_asset_downside_spillover_evaluation.v1"
EVIDENCE_DEPTH = "discovery"
PLANNED_CLAIMS = (
    "activity_and_concentration",
    "after_cost_fixed_lot_economics",
    "causal_feature_and_execution_validity",
    "registered_control_contrast",
    "selection_aware_signal_evidence",
    "temporal_and_regime_stability",
)
EVIDENCE_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "extreme_or_boundary",
    "regime_stability",
    "sensitivity_or_stress",
    "temporal_stability",
)


def _criterion(
    criterion_id: str,
    claim_id: str,
    evidence_mode: str,
    metric: str,
    operator: str,
    threshold: int,
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "criterion_id": criterion_id,
        "evidence_mode": evidence_mode,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
    }


CRITERIA = (
    _criterion(
        "A01-minimum-trades",
        "activity_and_concentration",
        "extreme_or_boundary",
        "trade_count",
        "ge",
        100,
    ),
    _criterion(
        "A02-positive-density",
        "activity_and_concentration",
        "extreme_or_boundary",
        "entries_per_day_milli",
        "gt",
        0,
    ),
    _criterion(
        "A03-profit-day-concentration",
        "activity_and_concentration",
        "extreme_or_boundary",
        "top5_profit_day_share_ppm",
        "le",
        400_000,
    ),
    _criterion(
        "B01-positive-native-cost",
        "after_cost_fixed_lot_economics",
        "cost_and_execution",
        "net_profit_micropoints",
        "gt",
        0,
    ),
    _criterion(
        "B02-fold-profit-factor",
        "after_cost_fixed_lot_economics",
        "cost_and_execution",
        "median_fold_profit_factor_milli",
        "ge",
        1_050,
    ),
    _criterion(
        "B03-slippage-stress",
        "after_cost_fixed_lot_economics",
        "sensitivity_or_stress",
        "stress_net_profit_micropoints",
        "ge",
        0,
    ),
    _criterion(
        "B04-monthly-realized-drawdown-share",
        "after_cost_fixed_lot_economics",
        "extreme_or_boundary",
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
        "le",
        500_000,
    ),
    _criterion(
        "C01-feature-prefix-invariance",
        "causal_feature_and_execution_validity",
        "causal_contrast",
        "prefix_invariance_mismatch_count",
        "eq",
        0,
    ),
    _criterion(
        "C02-decision-append-invariance",
        "causal_feature_and_execution_validity",
        "causal_contrast",
        "append_invariance_mismatch_count",
        "eq",
        0,
    ),
    _criterion(
        "C03-decision-time-causality",
        "causal_feature_and_execution_validity",
        "causal_contrast",
        "causality_violation_count",
        "eq",
        0,
    ),
    _criterion(
        "C04-resolved-cost",
        "causal_feature_and_execution_validity",
        "cost_and_execution",
        "unknown_cost_unresolved_signal_count",
        "eq",
        0,
    ),
    _criterion(
        "C05-finite-metrics",
        "causal_feature_and_execution_validity",
        "causal_contrast",
        "nonfinite_metric_count",
        "eq",
        0,
    ),
    _criterion(
        "D01-opposite-sign-control",
        "registered_control_contrast",
        "causal_contrast",
        "opposite_sign_worst_delta_net_profit_micropoints",
        "gt",
        0,
    ),
    _criterion(
        "D02-opposite-sign-uncertainty",
        "registered_control_contrast",
        "causal_contrast",
        "opposite_sign_pvalue_upper_ppm",
        "le",
        100_000,
    ),
    _criterion(
        "D03-feature-control",
        "registered_control_contrast",
        "causal_contrast",
        "feature_control_worst_delta_net_profit_micropoints",
        "gt",
        0,
    ),
    _criterion(
        "D04-feature-control-uncertainty",
        "registered_control_contrast",
        "causal_contrast",
        "feature_control_worst_pvalue_upper_ppm",
        "le",
        100_000,
    ),
    _criterion(
        "E01-familywise-selection",
        "selection_aware_signal_evidence",
        "temporal_stability",
        "selection_aware_pvalue_ppm",
        "le",
        100_000,
    ),
    _criterion(
        "F01-evaluable-folds",
        "temporal_and_regime_stability",
        "temporal_stability",
        "evaluable_folds",
        "ge",
        7,
    ),
    _criterion(
        "F02-winning-folds",
        "temporal_and_regime_stability",
        "temporal_stability",
        "winning_fold_count",
        "ge",
        5,
    ),
    _criterion(
        "F03-positive-regimes",
        "temporal_and_regime_stability",
        "regime_stability",
        "supported_positive_regime_count",
        "ge",
        2,
    ),
)


def build_cross_asset_downside_spillover_validation_plan(executable_id: str) -> dict[str, object]:
    return build_validation_plan(
        mission_id=MISSION_ID,
        executable_id=executable_id,
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=PLANNED_CLAIMS,
        evidence_modes=EVIDENCE_MODES,
        criteria=CRITERIA,
        candidate_eligible_on_pass=False,
    )


def _claim_metrics(evaluation: Mapping[str, Any]) -> dict[str, dict[str, int | None]]:
    raw = evaluation.get("metrics")
    if not isinstance(raw, Mapping):
        raise ValueError("cross_asset_downside_spillover evaluation has no metrics")
    metrics = {name: value for name, value in raw.items()}
    if any(type(name) is not str or type(value) is not int for name, value in metrics.items()):
        raise ValueError("cross_asset_downside_spillover evaluation metrics must be integer scalars")
    evaluable = evaluation.get("evaluable") is True

    def values(*names: str, null_when_not_evaluable: bool = False) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        for name in names:
            if name not in metrics:
                raise ValueError(f"cross_asset_downside_spillover evaluation metric is absent: {name}")
            result[name] = (
                None if null_when_not_evaluable and not evaluable else metrics[name]
            )
        return result

    return {
        "activity_and_concentration": values(
            "daily_entries_max_milli",
            "daily_entries_median_milli",
            "daily_entries_p10_milli",
            "daily_entries_p90_milli",
            "eligible_day_count",
            "entries_per_day_milli",
            "monthly_realized_exit_drawdown_micropoints",
            "top5_profit_day_share_ppm",
            "trade_count",
            "zero_entry_day_rate_ppm",
            null_when_not_evaluable=True,
        ),
        "after_cost_fixed_lot_economics": values(
            "median_fold_profit_factor_milli",
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
            "net_profit_micropoints",
            "stress_net_profit_micropoints",
            null_when_not_evaluable=True,
        ),
        "causal_feature_and_execution_validity": values(
            "append_invariance_mismatch_count",
            "causality_violation_count",
            "gap_excluded_signal_count",
            "nonfinite_metric_count",
            "prefix_invariance_mismatch_count",
            "unknown_cost_unresolved_signal_count",
        ),
        "registered_control_contrast": values(
            "feature_control_worst_delta_net_profit_micropoints",
            "feature_control_worst_pvalue_upper_ppm",
            "opposite_sign_pvalue_upper_ppm",
            "opposite_sign_worst_delta_net_profit_micropoints",
            null_when_not_evaluable=True,
        ),
        "selection_aware_signal_evidence": values(
            "selection_aware_pvalue_ppm",
            null_when_not_evaluable=True,
        ),
        "temporal_and_regime_stability": values(
            "evaluable_folds",
            "positive_regime_count",
            "supported_positive_regime_count",
            "winning_fold_count",
            null_when_not_evaluable=True,
        ),
    }


def build_measurement(
    *,
    executable_id: str,
    job_id: str,
    job_hash: str,
    evaluation_artifact_hash: str,
    evaluation: Mapping[str, Any],
) -> dict[str, object]:
    value: dict[str, object] = {
        "claims": list(PLANNED_CLAIMS),
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(EVIDENCE_MODES),
        "evaluation_artifact_hash": evaluation_artifact_hash,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "metrics": _claim_metrics(evaluation),
        "mission_id": MISSION_ID,
        "schema": SCIENTIFIC_MEASUREMENT_SCHEMA,
    }
    canonical_bytes(value)
    return value


def build_result_manifest(
    *,
    executable_id: str,
    job_id: str,
    job_hash: str,
    measurement_artifact_hash: str,
) -> dict[str, object]:
    value: dict[str, object] = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": MISSION_ID,
        "observations": [
            {
                "claim_id": claim,
                "measurement_artifact_hash": measurement_artifact_hash,
            }
            for claim in PLANNED_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


def planned_verdict(
    plan: Mapping[str, Any],
    measurement: Mapping[str, Any],
) -> str:
    """Predict the validator outcome only to choose the typed completion path."""

    metrics = measurement["metrics"]
    unavailable = False
    failed = False
    comparisons = {
        "eq": lambda value, threshold: value == threshold,
        "ge": lambda value, threshold: value >= threshold,
        "gt": lambda value, threshold: value > threshold,
        "le": lambda value, threshold: value <= threshold,
        "lt": lambda value, threshold: value < threshold,
    }
    for criterion in plan["criteria"]:
        value = metrics[criterion["claim_id"]][criterion["metric"]]
        if value is None:
            unavailable = True
        elif not comparisons[criterion["operator"]](value, criterion["threshold"]):
            failed = True
    if unavailable:
        return "not_evaluable"
    return "failed" if failed else "passed"


def output_names(executable_id: str) -> dict[str, str]:
    short = executable_id.removeprefix("executable:")[:16]
    prefix = f"scientific/{STUDY_ID}/{short}"
    return {
        "context": f"{prefix}/evaluation.json",
        "environment": f"{prefix}/environment.json",
        "measurement": f"{prefix}/measurement.json",
        "plan": f"{prefix}/validation-plan.json",
        "result": f"{prefix}/result.json",
    }


def surface_cache_output_name(repository_root: str | Path) -> str:
    raw_sha256 = us500_raw_sha256(Path(repository_root).resolve())
    return (
        f"local/cache/{STUDY_ID}/cross_asset_downside_spillover-surface-"
        f"{cross_asset_downside_spillover_implementation_sha256()[:12]}-"
        f"{raw_sha256[:12]}.json"
    )


def surface_manifest_output_name() -> str:
    return f"scientific/{STUDY_ID}/cross_asset_downside_spillover-surface-cache-manifest.json"


def _content_hash(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _validated_surface(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SURFACE_SCHEMA:
        raise ValueError("cross-asset downside-spillover surface schema is invalid")
    return value


def _source_provenance(repository_root: str | Path) -> dict[str, str]:
    root = Path(repository_root).resolve()
    source_contract_id = us500_source_contract().source_contract_id
    source_loader_hash = us500_source_implementation_sha256()
    if source_loader_hash != source_dependency_sha256():
        raise ValueError("US500 source loader hash differs from source qualification")
    value = {
        "source_contract_id": source_contract_id,
        "source_contract_sha256": source_contract_id.removeprefix("source:"),
        "source_raw_sha256": us500_raw_sha256(root),
        "source_loader_implementation_sha256": source_loader_hash,
        "source_study_implementation_sha256": source_study_implementation_sha256(),
        "source_validator_implementation_sha256": source_validator_implementation_sha256(),
        "scientific_validator_implementation_sha256": sha256(
            Path(scientific_validator_module.__file__).resolve().read_bytes()
        ).hexdigest(),
    }
    canonical_bytes(value)
    return value


def _registered_executable_ids(repository_root: str | Path) -> tuple[str, ...]:
    mapping = cross_asset_downside_spillover_executable_configuration_map(
        Path(repository_root).resolve()
    )
    if not isinstance(mapping, Mapping) or len(mapping) != 12:
        raise ValueError("cross_asset_downside_spillover Study requires exactly twelve Executables")
    identities = tuple(sorted(mapping))
    if any(
        type(identity) is not str
        or not identity.startswith("executable:")
        or len(identity) != 75
        for identity in identities
    ):
        raise ValueError("cross_asset_downside_spillover Study Executable identities are invalid")
    return identities


def build_environment_manifest(repository_root: str | Path) -> dict[str, object]:
    if SELECTION_TOTAL_EXPOSURES != 246:
        raise ValueError("cross_asset_downside_spillover Study requires global exposure total 246")
    source = _source_provenance(repository_root)
    value: dict[str, object] = {
        "dataset_sha256": DATASET_SHA256,
        "cross_asset_downside_spillover_implementation_sha256": cross_asset_downside_spillover_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "python_version": ".".join(str(item) for item in sys.version_info[:3]),
        "runner_implementation_sha256": sha256(
            Path(__file__).resolve().read_bytes()
        ).hexdigest(),
        "schema": "scientific_engine_environment.v1",
        "selection_total_exposures": SELECTION_TOTAL_EXPOSURES,
        "scipy_version": scipy.__version__,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trend_dependency_sha256": trend_dependency_sha256(),
        **source,
        "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
        "writer_implementation_sha256": sha256(
            Path(writer_module.__file__).resolve().read_bytes()
        ).hexdigest(),
    }
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class CrossAssetDownsideSpilloverJobPacket:
    artifact_bytes: tuple[tuple[str, bytes], ...]
    output_classes: tuple[tuple[str, str], ...]
    output_manifest: tuple[tuple[str, str], ...]
    surface_artifact_hash: str
    surface_manifest_hash: str
    verdict: str

    def artifact_hashes(self) -> dict[str, str]:
        return {
            name: sha256(content).hexdigest()
            for name, content in self.artifact_bytes
        }

    def artifact(self, name: str) -> dict[str, Any]:
        matches = [content for role, content in self.artifact_bytes if role == name]
        if len(matches) != 1:
            raise KeyError(name)
        value = parse_canonical(matches[0])
        if not isinstance(value, dict):
            raise ValueError("cross_asset_downside_spillover Job artifact is not an object")
        return value

    def completion_output_manifest(self) -> dict[str, str]:
        return dict(self.output_manifest)

    def completion_result_manifest(self) -> dict[str, Any]:
        return self.artifact("result")


def _materialize_cache(
    repository_root: Path,
    *,
    relative_name: str,
    content: bytes,
) -> None:
    target = (repository_root / relative_name).resolve()
    cache_root = (repository_root / "local" / "cache").resolve()
    if cache_root not in target.parents:
        raise ValueError("cross_asset_downside_spillover surface cache path escapes local/cache")
    expected_hash = sha256(content).hexdigest()
    if target.exists():
        if not target.is_file() or sha256(target.read_bytes()).hexdigest() != (
            expected_hash
        ):
            raise ValueError("existing cross_asset_downside_spillover surface cache has different bytes")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".cross_asset_downside_spillover-surface-",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_surface_manifest(
    *,
    repository_root: Path,
    cache_hash: str,
    environment_hash: str,
    execution: RunningJobExecution,
    producer_executable_id: str,
) -> dict[str, Any]:
    source = _source_provenance(repository_root)
    value: dict[str, Any] = {
        "cache_output_name": surface_cache_output_name(repository_root),
        "cache_sha256": cache_hash,
        "claim_authority": False,
        "dataset_sha256": DATASET_SHA256,
        "cross_asset_downside_spillover_implementation_sha256": cross_asset_downside_spillover_implementation_sha256(),
        "environment_sha256": environment_hash,
        "executable_ids": list(_registered_executable_ids(repository_root)),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "producer_execution": {
            **execution.payload(),
            "identity": execution.identity,
        },
        "producer_executable_id": producer_executable_id,
        "schema": "cross_asset_downside_spillover_surface_cache_manifest.v1",
        "selection_total_exposures": SELECTION_TOTAL_EXPOSURES,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trend_dependency_sha256": trend_dependency_sha256(),
        **source,
    }
    canonical_bytes(value)
    return value


def _validate_surface_manifest(
    value: object,
    *,
    repository_root: Path,
    cache_hash: str,
    environment_hash: str,
) -> dict[str, Any]:
    source = _source_provenance(repository_root)
    expected_fields = {
        "cache_output_name",
        "cache_sha256",
        "claim_authority",
        "dataset_sha256",
        "cross_asset_downside_spillover_implementation_sha256",
        "environment_sha256",
        "executable_ids",
        "loader_implementation_sha256",
        "material_identity",
        "producer_execution",
        "producer_executable_id",
        "schema",
        "selection_total_exposures",
        "split_artifact_sha256",
        "trend_dependency_sha256",
        *source,
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_fields
        or value.get("schema") != "cross_asset_downside_spillover_surface_cache_manifest.v1"
        or value.get("cache_output_name") != surface_cache_output_name(repository_root)
        or value.get("cache_sha256") != cache_hash
        or value.get("claim_authority") is not False
        or value.get("dataset_sha256") != DATASET_SHA256
        or value.get("cross_asset_downside_spillover_implementation_sha256")
        != cross_asset_downside_spillover_implementation_sha256()
        or value.get("environment_sha256") != environment_hash
        or value.get("executable_ids")
        != list(_registered_executable_ids(repository_root))
        or value.get("loader_implementation_sha256")
        != loader_implementation_sha256()
        or value.get("material_identity") != OBSERVED_MATERIAL_ID
        or value.get("producer_executable_id")
        not in _registered_executable_ids(repository_root)
        or value.get("selection_total_exposures") != 246
        or value.get("split_artifact_sha256") != ROLLING_SPLIT_SHA256
        or value.get("trend_dependency_sha256") != trend_dependency_sha256()
        or any(value.get(name) != expected for name, expected in source.items())
    ):
        raise ValueError("cross_asset_downside_spillover surface cache manifest differs from Job inputs")
    producer = value.get("producer_execution")
    if not isinstance(producer, dict) or set(producer) != {
        "identity",
        "job_hash",
        "job_id",
        "job_permit_id",
        "start_record_id",
    }:
        raise ValueError("cross_asset_downside_spillover surface producer execution is invalid")
    execution = RunningJobExecution.from_mapping(
        {
            name: producer[name]
            for name in (
                "job_hash",
                "job_id",
                "job_permit_id",
                "start_record_id",
            )
        }
    )
    if producer["identity"] != execution.identity:
        raise ValueError("cross_asset_downside_spillover surface producer identity is invalid")
    return value


def _load_surface_manifest(
    writer: StateWriter,
    *,
    repository_root: Path,
    input_hashes: tuple[str, ...],
    cache_hash: str,
    environment_hash: str,
) -> tuple[str, dict[str, Any]]:
    matches: list[tuple[str, dict[str, Any]]] = []
    for input_hash in input_hashes:
        try:
            artifact = writer.evidence.verify(input_hash)
            content = (
                writer.evidence._root / artifact.relative_path
            ).read_bytes()
            value = parse_canonical(content)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema") == (
            "cross_asset_downside_spillover_surface_cache_manifest.v1"
        ):
            matches.append(
                (
                    input_hash,
                    _validate_surface_manifest(
                        value,
                        repository_root=repository_root,
                        cache_hash=cache_hash,
                        environment_hash=environment_hash,
                    ),
                )
            )
    if len(matches) != 1:
        raise ValueError("Job inputs require one exact cross_asset_downside_spillover surface manifest")
    return matches[0]


def execute_cross_asset_downside_spillover_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> CrossAssetDownsideSpilloverJobPacket:
    """Run only from a writer-derived, Journal-verified Job capability."""

    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    spec = binding["spec"]
    evidence_subject = spec.get("evidence_subject")
    if (
        binding.get("mission_id") != MISSION_ID
        or binding.get("study_id") != STUDY_ID
        or not isinstance(evidence_subject, dict)
        or evidence_subject.get("kind") != "Executable"
        or evidence_subject.get("id") not in _registered_executable_ids(root)
    ):
        raise ValueError("running Job is not bound to the registered cross_asset_downside_spillover Study")
    executable_id = evidence_subject["id"]
    scientific_binding = spec.get("scientific_binding")
    if not isinstance(scientific_binding, dict):
        raise ValueError("cross_asset_downside_spillover Job lacks a scientific binding")
    plan = build_cross_asset_downside_spillover_validation_plan(executable_id)
    environment = build_environment_manifest(root)
    plan_hash = _content_hash(plan)
    environment_hash = _content_hash(environment)
    inputs = tuple(spec.get("input_hashes", []))
    source = _source_provenance(root)
    required_inputs = {
        DATASET_SHA256,
        OBSERVED_MATERIAL_ID,
        ROLLING_SPLIT_SHA256,
        cross_asset_downside_spillover_implementation_sha256(),
        environment_hash,
        environment["runner_implementation_sha256"],
        loader_implementation_sha256(),
        plan_hash,
        trend_dependency_sha256(),
        *(value for name, value in source.items() if name != "source_contract_id"),
    }
    if not required_inputs.issubset(inputs):
        raise ValueError("cross_asset_downside_spillover Job omits a required content-bound input")
    if scientific_binding.get("validation_plan_hash") != plan_hash:
        raise ValueError("cross_asset_downside_spillover validation plan differs from Job input")
    names = output_names(executable_id)
    if (
        scientific_binding.get("validator_id")
        != SCIENTIFIC_DISCOVERY_VALIDATOR_ID
        or scientific_binding.get("evidence_depth") != EVIDENCE_DEPTH
        or scientific_binding.get("evidence_modes") != list(EVIDENCE_MODES)
        or scientific_binding.get("planned_claims") != list(PLANNED_CLAIMS)
        or scientific_binding.get("result_manifest_output") != names["result"]
    ):
        raise ValueError("cross_asset_downside_spillover scientific binding differs from preregistration")
    expected_outputs = set(spec.get("expected_outputs", []))
    output_classes = spec.get("output_classes")
    if not isinstance(output_classes, dict):
        raise ValueError("cross_asset_downside_spillover Job output classes are invalid")
    durable_names = set(names.values())
    cache_name = surface_cache_output_name(root)
    manifest_name = surface_manifest_output_name()
    produces_surface = cache_name in expected_outputs
    expected_set = (
        durable_names | {cache_name, manifest_name}
        if produces_surface
        else durable_names
    )
    expected_classes = {
        **{name: "durable_evidence" for name in durable_names},
        **(
            {
                cache_name: "reproducible_cache",
                manifest_name: "durable_evidence",
            }
            if produces_surface
            else {}
        ),
    }
    if expected_outputs != expected_set or output_classes != expected_classes:
        raise ValueError("cross_asset_downside_spillover Job outputs differ from the producer/projector protocol")

    manifest_artifact_hash: str
    manifest_bytes: bytes | None = None
    if produces_surface:
        surface = _validated_surface(
            _compute_registered_cross_asset_downside_spillover_surface(root)
        )
        surface_bytes = canonical_bytes(surface)
        surface_hash = sha256(surface_bytes).hexdigest()
        _materialize_cache(root, relative_name=cache_name, content=surface_bytes)
        manifest = _build_surface_manifest(
            repository_root=root,
            cache_hash=surface_hash,
            environment_hash=environment_hash,
            execution=execution,
            producer_executable_id=executable_id,
        )
        manifest_bytes = canonical_bytes(manifest)
        manifest_artifact_hash = writer.evidence.finalize(
            manifest_bytes
        ).sha256
    else:
        cache_target = (root / cache_name).resolve()
        if not cache_target.is_file():
            raise ValueError("cross_asset_downside_spillover surface cache is unavailable")
        surface_bytes = cache_target.read_bytes()
        surface_hash = sha256(surface_bytes).hexdigest()
        if surface_hash not in inputs:
            raise ValueError("cross_asset_downside_spillover surface cache hash is not a Job input")
        manifest_artifact_hash, cache_manifest = _load_surface_manifest(
            writer,
            repository_root=root,
            input_hashes=inputs,
            cache_hash=surface_hash,
            environment_hash=environment_hash,
        )
        producer_payload = cache_manifest["producer_execution"]
        producer_executable_id = cache_manifest["producer_executable_id"]
        producer = RunningJobExecution.from_mapping(
            {
                name: producer_payload[name]
                for name in (
                    "job_hash",
                    "job_id",
                    "job_permit_id",
                    "start_record_id",
                )
            }
        )
        writer.verify_reproducible_cache_producer(
            producer,
            cache_output_name=cache_name,
            cache_hash=surface_hash,
            expected_callable_identity=CALLABLE_IDENTITY,
            expected_evidence_subject={
                "kind": "Executable",
                "id": producer_executable_id,
            },
            expected_output_classes={
                **{
                    name: "durable_evidence"
                    for name in output_names(producer_executable_id).values()
                },
                cache_name: "reproducible_cache",
                manifest_name: "durable_evidence",
            },
            expected_study_id=STUDY_ID,
            manifest_output_name=manifest_name,
            manifest_hash=manifest_artifact_hash,
        )
        surface = _validated_surface(parse_canonical(surface_bytes))

    context = project_cross_asset_downside_spillover_evaluation(
        surface,
        job_execution={**execution.payload(), "identity": execution.identity},
        subject_executable_id=executable_id,
        surface_artifact_hash=surface_hash,
        surface_manifest_hash=manifest_artifact_hash,
    )
    if not isinstance(context, dict) or context.get("schema") != EVALUATION_SCHEMA:
        raise ValueError("cross-asset downside-spillover evaluation schema is invalid")
    context_hash = _content_hash(context)
    measurement = build_measurement(
        executable_id=executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        evaluation_artifact_hash=context_hash,
        evaluation=context,
    )
    measurement_hash = _content_hash(measurement)
    result = build_result_manifest(
        executable_id=executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_artifact_hash=measurement_hash,
    )
    artifacts = {
        "context": canonical_bytes(context),
        "environment": canonical_bytes(environment),
        "measurement": canonical_bytes(measurement),
        "plan": canonical_bytes(plan),
        "result": canonical_bytes(result),
    }
    output_manifest = {
        names[role]: writer.evidence.finalize(content).sha256
        for role, content in artifacts.items()
    }
    if produces_surface:
        output_manifest[cache_name] = surface_hash
        output_manifest[manifest_name] = manifest_artifact_hash
    if set(output_manifest) != expected_outputs:
        raise ValueError("materialized cross_asset_downside_spillover outputs differ from Job declaration")
    return CrossAssetDownsideSpilloverJobPacket(
        artifact_bytes=tuple(sorted(artifacts.items())),
        output_classes=tuple(sorted(output_classes.items())),
        output_manifest=tuple(sorted(output_manifest.items())),
        surface_artifact_hash=surface_hash,
        surface_manifest_hash=manifest_artifact_hash,
        verdict=planned_verdict(plan, measurement),
    )


__all__ = [
    "CRITERIA",
    "CALLABLE_IDENTITY",
    "EVIDENCE_DEPTH",
    "EVALUATION_SCHEMA",
    "EVIDENCE_MODES",
    "MISSION_ID",
    "PLANNED_CLAIMS",
    "SURFACE_SCHEMA",
    "SELECTION_TOTAL_EXPOSURES",
    "build_measurement",
    "build_environment_manifest",
    "build_result_manifest",
    "build_cross_asset_downside_spillover_validation_plan",
    "output_names",
    "planned_verdict",
    "execute_cross_asset_downside_spillover_job",
    "surface_cache_output_name",
    "surface_manifest_output_name",
    "CrossAssetDownsideSpilloverJobPacket",
]
