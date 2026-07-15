"""Reusable Writer-gated evidence Job for fold-trained analog states."""

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
from axiom_rift.research.analog_state_discovery import (
    analog_implementation_sha256,
    compute_registered_analog_surface,
    executable_configuration_map,
    loader_implementation_sha256,
    project_analog_evaluation,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    discovery_implementation_sha256,
)
from axiom_rift.research.evidence_inputs import (
    read_surface_manifest_evidence_inputs,
)
from axiom_rift.research.trend_study import (
    CRITERIA,
    EVIDENCE_MODES,
    PLANNED_CLAIMS,
    _claim_metrics,
    planned_verdict,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    SCIENTIFIC_MEASUREMENT_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    build_validation_plan,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.analog_state_study.execute_analog_job.v3"
)
EVIDENCE_DEPTH = "discovery"


def _control_id(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def build_analog_validation_plan(
    executable_id: str,
    *,
    mission_id: str,
) -> dict[str, object]:
    return build_validation_plan(
        mission_id=_control_id("mission_id", mission_id),
        executable_id=executable_id,
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=PLANNED_CLAIMS,
        evidence_modes=EVIDENCE_MODES,
        criteria=CRITERIA,
        candidate_eligible_on_pass=False,
    )


def output_names(executable_id: str, *, study_id: str) -> dict[str, str]:
    study = _control_id("study_id", study_id)
    prefix = f"scientific/{study}/{executable_id.removeprefix('executable:')[:16]}"
    return {
        "context": f"{prefix}/evaluation.json",
        "environment": f"{prefix}/environment.json",
        "measurement": f"{prefix}/measurement.json",
        "plan": f"{prefix}/validation-plan.json",
        "result": f"{prefix}/result.json",
    }


def surface_output_name(*, study_id: str) -> str:
    return f"scientific/{_control_id('study_id', study_id)}/analog-state-surface.json"


def surface_manifest_output_name(*, study_id: str) -> str:
    return (
        f"scientific/{_control_id('study_id', study_id)}/"
        "analog-state-surface-manifest.json"
    )


def build_environment_manifest() -> dict[str, object]:
    value = {
        "analog_implementation_sha256": analog_implementation_sha256(),
        "dataset_sha256": DATASET_SHA256,
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "python_version": ".".join(str(item) for item in sys.version_info[:3]),
        "runner_implementation_sha256": sha256(
            Path(__file__).resolve().read_bytes()
        ).hexdigest(),
        "schema": "scientific_engine_environment.v1",
        "scipy_version": scipy.__version__,
        "shared_discovery_implementation_sha256": (
            discovery_implementation_sha256()
        ),
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
        "running_job_context_implementation_sha256": running_job_execution_context_implementation_sha256(),
    }
    canonical_bytes(value)
    return value


def build_measurement(
    *,
    executable_id: str,
    mission_id: str,
    job_id: str,
    job_hash: str,
    evaluation_artifact_hash: str,
    evaluation: Mapping[str, Any],
) -> dict[str, object]:
    value = {
        "claims": list(PLANNED_CLAIMS),
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(EVIDENCE_MODES),
        "evaluation_artifact_hash": evaluation_artifact_hash,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "metrics": _claim_metrics(evaluation),
        "mission_id": _control_id("mission_id", mission_id),
        "schema": SCIENTIFIC_MEASUREMENT_SCHEMA,
    }
    canonical_bytes(value)
    return value


def build_result_manifest(
    *,
    executable_id: str,
    mission_id: str,
    job_id: str,
    job_hash: str,
    measurement_artifact_hash: str,
) -> dict[str, object]:
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": _control_id("mission_id", mission_id),
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


@dataclass(frozen=True, slots=True)
class AnalogJobPacket:
    output_manifest: tuple[tuple[str, str], ...]
    verdict: str

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def _load_surface(
    writer: RunningJobExecutionContext,
    hashes: tuple[str, ...],
) -> tuple[dict[str, Any], str, str]:
    binding = read_surface_manifest_evidence_inputs(
        writer.evidence,
        hashes,
        surface_schema="analog_state_surface.v2",
        manifest_schema="analog_state_surface_manifest.v2",
        expected_surface_implementation_sha256=analog_implementation_sha256(),
    )
    return (
        binding.surface.value,
        binding.surface.artifact_sha256,
        binding.manifest.artifact_sha256,
    )


def execute_analog_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> AnalogJobPacket:
    root = Path(repository_root).resolve()
    writer = RunningJobExecutionContext(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    spec = binding["spec"]
    subject = spec.get("evidence_subject")
    mission_id = _control_id("mission_id", binding.get("mission_id"))
    study_id = _control_id("study_id", binding.get("study_id"))
    if (
        not isinstance(subject, dict)
        or subject.get("id") not in executable_configuration_map()
    ):
        raise ValueError("analog Job subject binding is invalid")

    executable_id = subject["id"]
    plan = build_analog_validation_plan(
        executable_id,
        mission_id=mission_id,
    )
    environment = build_environment_manifest()
    plan_hash = sha256(canonical_bytes(plan)).hexdigest()
    names = output_names(executable_id, study_id=study_id)
    inputs = tuple(spec["input_hashes"])
    required = {
        DATASET_SHA256,
        OBSERVED_MATERIAL_ID,
        ROLLING_SPLIT_SHA256,
        plan_hash,
        analog_implementation_sha256(),
        loader_implementation_sha256(),
        discovery_implementation_sha256(),
    }
    if not required.issubset(inputs):
        raise ValueError("analog Job inputs omit a registered dependency")

    surface_name = surface_output_name(study_id=study_id)
    surface_manifest_name = surface_manifest_output_name(study_id=study_id)
    expected_outputs = set(spec["expected_outputs"])
    produces_surface = surface_name in expected_outputs
    if produces_surface:
        surface = compute_registered_analog_surface(root)
        surface_hash = writer.evidence.finalize(canonical_bytes(surface)).sha256
        surface_manifest_hash = writer.evidence.finalize(
            canonical_bytes(
                {
                    "schema": "analog_state_surface_manifest.v2",
                    "surface_artifact_hash": surface_hash,
                    "surface_implementation_sha256": (
                        analog_implementation_sha256()
                    ),
                }
            )
        ).sha256
    else:
        surface, surface_hash, surface_manifest_hash = _load_surface(
            writer,
            tuple(identity for identity in inputs if identity not in required),
        )

    evaluation = project_analog_evaluation(
        surface,
        job_execution={**execution.payload(), "identity": execution.identity},
        subject_executable_id=executable_id,
        surface_artifact_hash=surface_hash,
        surface_manifest_hash=surface_manifest_hash,
    )
    evaluation_hash = writer.evidence.finalize(
        canonical_bytes(evaluation)
    ).sha256
    measurement = build_measurement(
        executable_id=executable_id,
        mission_id=mission_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        evaluation_artifact_hash=evaluation_hash,
        evaluation=evaluation,
    )
    measurement_hash = writer.evidence.finalize(
        canonical_bytes(measurement)
    ).sha256
    result = build_result_manifest(
        executable_id=executable_id,
        mission_id=mission_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_artifact_hash=measurement_hash,
    )
    outputs = {
        names["context"]: evaluation_hash,
        names["environment"]: writer.evidence.finalize(
            canonical_bytes(environment)
        ).sha256,
        names["measurement"]: measurement_hash,
        names["plan"]: writer.evidence.finalize(canonical_bytes(plan)).sha256,
        names["result"]: writer.evidence.finalize(canonical_bytes(result)).sha256,
    }
    if produces_surface:
        outputs[surface_name] = surface_hash
        outputs[surface_manifest_name] = surface_manifest_hash
    return AnalogJobPacket(
        output_manifest=tuple(sorted(outputs.items())),
        verdict=planned_verdict(plan, measurement),
    )


__all__ = [
    "CALLABLE_IDENTITY",
    "EVIDENCE_DEPTH",
    "EVIDENCE_MODES",
    "PLANNED_CLAIMS",
    "AnalogJobPacket",
    "build_analog_validation_plan",
    "build_environment_manifest",
    "build_measurement",
    "build_result_manifest",
    "execute_analog_job",
    "output_names",
    "surface_manifest_output_name",
    "surface_output_name",
]
