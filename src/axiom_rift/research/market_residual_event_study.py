"""Writer-gated evidence Job for the fixed market-residual event contrast."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.running_job_context import (
    RunningJobExecutionContext,
    running_job_execution_context_implementation_sha256,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    discovery_implementation_sha256,
)
from axiom_rift.research.high_vol_target_reversal_chassis import (
    loader_implementation_sha256,
)
from axiom_rift.research.market_residual_event_chassis import (
    US500_RAW_SHA256,
    market_residual_event_chassis_implementation_sha256,
    market_residual_event_configurations,
    market_residual_event_executable,
)
from axiom_rift.research.market_residual_event_discovery import (
    compute_registered_market_residual_event_surface,
    market_residual_event_discovery_implementation_sha256,
    project_market_residual_event_evaluation,
)
from axiom_rift.research.scientific_study import (
    EVIDENCE_MODES,
    PLANNED_CLAIMS,
    claim_metrics,
    discovery_criteria,
    planned_verdict,
)
from axiom_rift.research.us500_source import us500_source_contract
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    SCIENTIFIC_MEASUREMENT_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    build_validation_plan,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.market_residual_event_study."
    "execute_market_residual_event_job.v1"
)
EVIDENCE_DEPTH = "discovery"
_DELTA = "target_only_delta_net_profit_micropoints"
_PVALUE = "target_only_pvalue_upper_ppm"
CRITERIA = discovery_criteria(
    control_delta_metric=_DELTA,
    control_pvalue_metric=_PVALUE,
    include_opposite_sign=False,
)


def executable_configuration_map():
    return {
        market_residual_event_executable(configuration).identity: configuration
        for configuration in market_residual_event_configurations()
    }


def build_market_residual_event_validation_plan(
    executable_id: str,
    *,
    mission_id: str,
) -> dict[str, object]:
    return build_validation_plan(
        mission_id=mission_id,
        executable_id=executable_id,
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=PLANNED_CLAIMS,
        evidence_modes=EVIDENCE_MODES,
        criteria=CRITERIA,
        candidate_eligible_on_pass=False,
    )


def output_names(executable_id: str, *, study_id: str) -> dict[str, str]:
    prefix = f"scientific/{study_id}/{executable_id.removeprefix('executable:')[:16]}"
    return {
        "context": f"{prefix}/evaluation.json",
        "environment": f"{prefix}/environment.json",
        "measurement": f"{prefix}/measurement.json",
        "plan": f"{prefix}/validation-plan.json",
        "result": f"{prefix}/result.json",
    }


def surface_output_name(*, study_id: str) -> str:
    return f"scientific/{study_id}/market-residual-event-surface.json"


def surface_manifest_output_name(*, study_id: str) -> str:
    return f"scientific/{study_id}/market-residual-event-surface-manifest.json"


def build_environment_manifest() -> dict[str, object]:
    contract = us500_source_contract()
    value = {
        "schema": "scientific_engine_environment.v1",
        "dataset_sha256": DATASET_SHA256,
        "material_identity": OBSERVED_MATERIAL_ID,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "source_contract_id": contract.source_contract_id,
        "source_mapping_identity": contract.mapping_identity,
        "source_schema_identity": contract.schema_identity,
        "source_field_identity": contract.field_identity,
        "source_clock_identity": contract.clock_identity,
        "source_availability_identity": contract.availability_identity,
        "source_raw_sha256": US500_RAW_SHA256,
        "loader_implementation_sha256": loader_implementation_sha256(),
        "shared_discovery_implementation_sha256": discovery_implementation_sha256(),
        "market_residual_event_chassis_implementation_sha256": (
            market_residual_event_chassis_implementation_sha256()
        ),
        "market_residual_event_discovery_implementation_sha256": (
            market_residual_event_discovery_implementation_sha256()
        ),
        "runner_implementation_sha256": sha256(
            Path(__file__).resolve().read_bytes()
        ).hexdigest(),
        "running_job_context_implementation_sha256": running_job_execution_context_implementation_sha256(),
        "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "scipy_version": scipy.__version__,
    }
    canonical_bytes(value)
    return value


def _metrics(evaluation: Mapping[str, Any]) -> dict[str, dict[str, int | None]]:
    return claim_metrics(
        evaluation,
        control_delta_metric=_DELTA,
        control_pvalue_metric=_PVALUE,
        include_opposite_sign=False,
    )


def build_measurement(
    *,
    executable_id: str,
    job_id: str,
    job_hash: str,
    evaluation_artifact_hash: str,
    evaluation: Mapping[str, Any],
    mission_id: str,
) -> dict[str, object]:
    value = {
        "schema": SCIENTIFIC_MEASUREMENT_SCHEMA,
        "claims": list(PLANNED_CLAIMS),
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(EVIDENCE_MODES),
        "evaluation_artifact_hash": evaluation_artifact_hash,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "metrics": _metrics(evaluation),
        "mission_id": mission_id,
    }
    canonical_bytes(value)
    return value


def build_result_manifest(
    *,
    executable_id: str,
    job_id: str,
    job_hash: str,
    measurement_artifact_hash: str,
    mission_id: str,
) -> dict[str, object]:
    value = {
        "schema": SCIENTIFIC_RESULT_SCHEMA,
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": mission_id,
        "observations": [
            {
                "claim_id": claim,
                "measurement_artifact_hash": measurement_artifact_hash,
            }
            for claim in PLANNED_CLAIMS
        ],
    }
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class MarketResidualEventJobPacket:
    output_manifest: tuple[tuple[str, str], ...]
    verdict: str

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def execute_market_residual_event_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> MarketResidualEventJobPacket:
    root = Path(repository_root).resolve()
    writer = RunningJobExecutionContext(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    spec = binding["spec"]
    subject = spec.get("evidence_subject")
    mission_id = binding.get("mission_id")
    study_id = binding.get("study_id")
    configurations = executable_configuration_map()
    if (
        not isinstance(mission_id, str)
        or not isinstance(study_id, str)
        or not isinstance(subject, dict)
        or subject.get("id") not in configurations
    ):
        raise ValueError("market residual event binding is invalid")
    executable_id = subject["id"]
    plan = build_market_residual_event_validation_plan(
        executable_id,
        mission_id=mission_id,
    )
    plan_hash = sha256(canonical_bytes(plan)).hexdigest()
    names = output_names(executable_id, study_id=study_id)
    contract = us500_source_contract()
    required = {
        DATASET_SHA256,
        OBSERVED_MATERIAL_ID,
        ROLLING_SPLIT_SHA256,
        US500_RAW_SHA256,
        contract.source_contract_id.removeprefix("source:"),
        contract.mapping_identity,
        contract.schema_identity,
        contract.field_identity,
        contract.clock_identity,
        contract.availability_identity,
        plan_hash,
        market_residual_event_chassis_implementation_sha256(),
        market_residual_event_discovery_implementation_sha256(),
        loader_implementation_sha256(),
        discovery_implementation_sha256(),
    }
    if not required.issubset(spec["input_hashes"]):
        raise ValueError("market residual event Job inputs are incomplete")
    surface = compute_registered_market_residual_event_surface(root)
    surface_hash = writer.evidence.finalize(canonical_bytes(surface)).sha256
    surface_manifest = {
        "schema": "market_residual_event_surface_manifest.v1",
        "surface_artifact_hash": surface_hash,
        "surface_implementation_sha256": (
            market_residual_event_discovery_implementation_sha256()
        ),
    }
    surface_manifest_hash = writer.evidence.finalize(
        canonical_bytes(surface_manifest)
    ).sha256
    evaluation = project_market_residual_event_evaluation(
        surface,
        job_execution={**execution.payload(), "identity": execution.identity},
        subject_executable_id=executable_id,
        surface_artifact_hash=surface_hash,
        surface_manifest_hash=surface_manifest_hash,
    )
    evaluation_hash = writer.evidence.finalize(canonical_bytes(evaluation)).sha256
    measurement = build_measurement(
        executable_id=executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        evaluation_artifact_hash=evaluation_hash,
        evaluation=evaluation,
        mission_id=mission_id,
    )
    measurement_hash = writer.evidence.finalize(canonical_bytes(measurement)).sha256
    result = build_result_manifest(
        executable_id=executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_artifact_hash=measurement_hash,
        mission_id=mission_id,
    )
    outputs = {
        names["context"]: evaluation_hash,
        names["environment"]: writer.evidence.finalize(
            canonical_bytes(build_environment_manifest())
        ).sha256,
        names["measurement"]: measurement_hash,
        names["plan"]: writer.evidence.finalize(canonical_bytes(plan)).sha256,
        names["result"]: writer.evidence.finalize(canonical_bytes(result)).sha256,
        surface_output_name(study_id=study_id): surface_hash,
        surface_manifest_output_name(study_id=study_id): surface_manifest_hash,
    }
    return MarketResidualEventJobPacket(
        output_manifest=tuple(sorted(outputs.items())),
        verdict=planned_verdict(plan, measurement),
    )


__all__ = [
    "CALLABLE_IDENTITY",
    "CRITERIA",
    "EVIDENCE_DEPTH",
    "EVIDENCE_MODES",
    "PLANNED_CLAIMS",
    "build_environment_manifest",
    "build_market_residual_event_validation_plan",
    "execute_market_residual_event_job",
    "executable_configuration_map",
    "output_names",
    "surface_manifest_output_name",
    "surface_output_name",
]
