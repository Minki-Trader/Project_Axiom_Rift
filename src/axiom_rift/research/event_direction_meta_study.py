"""Writer-gated evidence Job for the event direction meta-policy."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy
import sklearn

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations import writer as writer_module
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    discovery_implementation_sha256,
)
from axiom_rift.research.event_direction_meta_chassis import (
    executable_configuration_map,
    event_direction_meta_chassis_implementation_sha256,
)
from axiom_rift.research.event_direction_meta_discovery import (
    compute_registered_event_direction_meta_surface,
    event_direction_meta_discovery_implementation_sha256,
    project_event_direction_meta_evaluation,
)
from axiom_rift.research.scientific_study import (
    EVIDENCE_MODES,
    PLANNED_CLAIMS,
    claim_metrics,
    discovery_criteria,
    planned_verdict,
)
from axiom_rift.research.session_dense_positive_sleeve_chassis import (
    loader_implementation_sha256,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    SCIENTIFIC_MEASUREMENT_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    build_validation_plan,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.event_direction_meta_study."
    "execute_event_direction_meta_job.v1"
)
EVIDENCE_DEPTH = "discovery"
_DELTA = "stu0092_control_delta_net_profit_micropoints"
_PVALUE = "stu0092_control_pvalue_upper_ppm"
_BASE_CRITERIA = discovery_criteria(
    control_delta_metric=_DELTA,
    control_pvalue_metric=_PVALUE,
    include_opposite_sign=False,
)
_INVARIANCE_CRITERIA = (
    {
        "claim_id": "causal_feature_and_execution_validity",
        "criterion_id": "C06-event-intent-schedule-invariance",
        "evidence_mode": "causal_contrast",
        "metric": "event_schedule_mismatch_count",
        "operator": "eq",
        "threshold": 0,
    },
    {
        "claim_id": "causal_feature_and_execution_validity",
        "criterion_id": "C07-executed-event-schedule-invariance",
        "evidence_mode": "causal_contrast",
        "metric": "executed_event_schedule_mismatch_count",
        "operator": "eq",
        "threshold": 0,
    },
    {
        "claim_id": "causal_feature_and_execution_validity",
        "criterion_id": "C08-event-count-invariance",
        "evidence_mode": "causal_contrast",
        "metric": "event_count_delta_abs",
        "operator": "eq",
        "threshold": 0,
    },
    {
        "claim_id": "causal_feature_and_execution_validity",
        "criterion_id": "C09-slot-hold-invariance",
        "evidence_mode": "causal_contrast",
        "metric": "slot_hold_mismatch_count",
        "operator": "eq",
        "threshold": 0,
    },
    {
        "claim_id": "causal_feature_and_execution_validity",
        "criterion_id": "C10-no-direction-abstention",
        "evidence_mode": "causal_contrast",
        "metric": "direction_action_missing_count",
        "operator": "eq",
        "threshold": 0,
    },
)
CRITERIA = tuple(
    sorted(
        (*_BASE_CRITERIA, *_INVARIANCE_CRITERIA),
        key=lambda item: (str(item["claim_id"]), str(item["criterion_id"])),
    )
)


def build_event_direction_meta_validation_plan(
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
    return f"scientific/{study_id}/event-direction-meta-surface.json"


def surface_manifest_output_name(*, study_id: str) -> str:
    return f"scientific/{study_id}/event-direction-meta-surface-manifest.json"


def build_environment_manifest() -> dict[str, object]:
    value = {
        "dataset_sha256": DATASET_SHA256,
        "event_direction_meta_chassis_implementation_sha256": (
            event_direction_meta_chassis_implementation_sha256()
        ),
        "event_direction_meta_discovery_implementation_sha256": (
            event_direction_meta_discovery_implementation_sha256()
        ),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "runner_implementation_sha256": sha256(
            Path(__file__).resolve().read_bytes()
        ).hexdigest(),
        "schema": "scientific_engine_environment.v1",
        "scipy_version": scipy.__version__,
        "shared_discovery_implementation_sha256": discovery_implementation_sha256(),
        "sklearn_version": sklearn.__version__,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
        "writer_implementation_sha256": sha256(
            Path(writer_module.__file__).resolve().read_bytes()
        ).hexdigest(),
    }
    canonical_bytes(value)
    return value


def _metrics(
    evaluation: Mapping[str, Any],
) -> dict[str, dict[str, int | None]]:
    values = claim_metrics(
        evaluation,
        control_delta_metric=_DELTA,
        control_pvalue_metric=_PVALUE,
        include_opposite_sign=False,
    )
    raw = evaluation.get("metrics")
    if not isinstance(raw, Mapping):
        raise ValueError("event direction evaluation has no metrics")
    causal = values["causal_feature_and_execution_validity"]
    for name in (
        "direction_action_missing_count",
        "event_count_delta_abs",
        "event_schedule_mismatch_count",
        "executed_event_schedule_mismatch_count",
        "slot_hold_mismatch_count",
    ):
        value = raw.get(name)
        if type(value) is not int:
            raise ValueError("event direction invariant metric is invalid")
        causal[name] = value
    return values


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
        "claims": list(PLANNED_CLAIMS),
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(EVIDENCE_MODES),
        "evaluation_artifact_hash": evaluation_artifact_hash,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "metrics": _metrics(evaluation),
        "mission_id": mission_id,
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
    mission_id: str,
) -> dict[str, object]:
    value = {
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
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class EventDirectionMetaJobPacket:
    output_manifest: tuple[tuple[str, str], ...]
    verdict: str

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def _load(
    writer: StateWriter,
    inputs: tuple[str, ...],
) -> tuple[dict[str, Any], str, str]:
    surface = None
    manifest = None
    for artifact_hash in inputs:
        try:
            artifact = writer.evidence.verify(artifact_hash)
            value = parse_canonical(
                (writer.evidence._root / artifact.relative_path).read_bytes()
            )
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema") == (
            "event_direction_meta_surface.v1"
        ):
            surface = (value, artifact_hash)
        if isinstance(value, dict) and value.get("schema") == (
            "event_direction_meta_surface_manifest.v1"
        ):
            manifest = (value, artifact_hash)
    if (
        surface is None
        or manifest is None
        or manifest[0].get("surface_artifact_hash") != surface[1]
    ):
        raise ValueError("event direction meta surface is missing")
    return surface[0], surface[1], manifest[1]


def execute_event_direction_meta_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> EventDirectionMetaJobPacket:
    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    spec = binding["spec"]
    subject = spec.get("evidence_subject")
    mission_id = binding.get("mission_id")
    study_id = binding.get("study_id")
    if (
        not isinstance(mission_id, str)
        or not isinstance(study_id, str)
        or not isinstance(subject, dict)
        or subject.get("id") not in executable_configuration_map()
    ):
        raise ValueError("event direction meta binding is invalid")
    executable_id = subject["id"]
    plan = build_event_direction_meta_validation_plan(
        executable_id,
        mission_id=mission_id,
    )
    plan_hash = sha256(canonical_bytes(plan)).hexdigest()
    names = output_names(executable_id, study_id=study_id)
    inputs = tuple(spec["input_hashes"])
    required = {
        DATASET_SHA256,
        OBSERVED_MATERIAL_ID,
        ROLLING_SPLIT_SHA256,
        plan_hash,
        event_direction_meta_chassis_implementation_sha256(),
        event_direction_meta_discovery_implementation_sha256(),
        loader_implementation_sha256(),
        discovery_implementation_sha256(),
    }
    if not required.issubset(inputs):
        raise ValueError("event direction meta inputs are missing")
    produces = surface_output_name(study_id=study_id) in set(
        spec["expected_outputs"]
    )
    if produces:
        surface = compute_registered_event_direction_meta_surface(root)
        surface_hash = writer.evidence.finalize(canonical_bytes(surface)).sha256
        manifest_value = {
            "schema": "event_direction_meta_surface_manifest.v1",
            "surface_artifact_hash": surface_hash,
            "surface_implementation_sha256": (
                event_direction_meta_discovery_implementation_sha256()
            ),
        }
        manifest_hash = writer.evidence.finalize(
            canonical_bytes(manifest_value)
        ).sha256
    else:
        surface, surface_hash, manifest_hash = _load(writer, inputs)
    evaluation = project_event_direction_meta_evaluation(
        surface,
        job_execution={**execution.payload(), "identity": execution.identity},
        subject_executable_id=executable_id,
        surface_artifact_hash=surface_hash,
        surface_manifest_hash=manifest_hash,
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
    }
    if produces:
        outputs[surface_output_name(study_id=study_id)] = surface_hash
        outputs[surface_manifest_output_name(study_id=study_id)] = manifest_hash
    return EventDirectionMetaJobPacket(
        tuple(sorted(outputs.items())),
        planned_verdict(plan, measurement),
    )


__all__ = [
    "CALLABLE_IDENTITY",
    "CRITERIA",
    "EVIDENCE_DEPTH",
    "EVIDENCE_MODES",
    "PLANNED_CLAIMS",
    "build_environment_manifest",
    "build_event_direction_meta_validation_plan",
    "execute_event_direction_meta_job",
    "output_names",
    "surface_manifest_output_name",
    "surface_output_name",
]
