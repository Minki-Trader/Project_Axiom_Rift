"""Writer-gated evidence Job for session-dense positive sleeves."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations import writer as writer_module
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research.discovery import DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, discovery_implementation_sha256
from axiom_rift.research.scientific_study import EVIDENCE_MODES, PLANNED_CLAIMS, claim_metrics, discovery_criteria, planned_verdict
from axiom_rift.research.session_dense_positive_sleeve_chassis import executable_configuration_map, loader_implementation_sha256, session_dense_positive_sleeve_chassis_implementation_sha256
from axiom_rift.research.session_dense_positive_sleeve_discovery import compute_registered_session_dense_positive_sleeve_surface, project_session_dense_positive_sleeve_evaluation, session_dense_positive_sleeve_discovery_implementation_sha256
from axiom_rift.research.validation import SCIENTIFIC_DISCOVERY_VALIDATOR_ID, SCIENTIFIC_MEASUREMENT_SCHEMA, SCIENTIFIC_RESULT_SCHEMA, build_validation_plan


CALLABLE_IDENTITY = "axiom_rift.research.session_dense_positive_sleeve_study.execute_session_dense_positive_sleeve_job.v1"
EVIDENCE_DEPTH = "discovery"
_DELTA = "router_control_delta_net_profit_micropoints"
_PVALUE = "router_control_pvalue_upper_ppm"
CRITERIA = discovery_criteria(control_delta_metric=_DELTA, control_pvalue_metric=_PVALUE, include_opposite_sign=False)


def build_session_dense_positive_sleeve_validation_plan(executable_id: str, *, mission_id: str) -> dict[str, object]:
    return build_validation_plan(mission_id=mission_id, executable_id=executable_id, evidence_depth=EVIDENCE_DEPTH, planned_claims=PLANNED_CLAIMS, evidence_modes=EVIDENCE_MODES, criteria=CRITERIA, candidate_eligible_on_pass=False)


def output_names(executable_id: str, *, study_id: str) -> dict[str, str]:
    prefix = f"scientific/{study_id}/{executable_id.removeprefix('executable:')[:16]}"
    return {"context": f"{prefix}/evaluation.json", "environment": f"{prefix}/environment.json", "measurement": f"{prefix}/measurement.json", "plan": f"{prefix}/validation-plan.json", "result": f"{prefix}/result.json"}


def surface_output_name(*, study_id: str) -> str:
    return f"scientific/{study_id}/session-dense-positive-sleeve-surface.json"


def surface_manifest_output_name(*, study_id: str) -> str:
    return f"scientific/{study_id}/session-dense-positive-sleeve-surface-manifest.json"


def build_environment_manifest() -> dict[str, object]:
    value = {"dataset_sha256": DATASET_SHA256, "loader_implementation_sha256": loader_implementation_sha256(), "material_identity": OBSERVED_MATERIAL_ID, "numpy_version": np.__version__, "pandas_version": pd.__version__, "python_version": ".".join(str(value) for value in sys.version_info[:3]), "runner_implementation_sha256": sha256(Path(__file__).resolve().read_bytes()).hexdigest(), "schema": "scientific_engine_environment.v1", "scipy_version": scipy.__version__, "session_dense_positive_sleeve_chassis_implementation_sha256": session_dense_positive_sleeve_chassis_implementation_sha256(), "session_dense_positive_sleeve_discovery_implementation_sha256": session_dense_positive_sleeve_discovery_implementation_sha256(), "shared_discovery_implementation_sha256": discovery_implementation_sha256(), "split_artifact_sha256": ROLLING_SPLIT_SHA256, "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID, "writer_implementation_sha256": sha256(Path(writer_module.__file__).resolve().read_bytes()).hexdigest()}
    canonical_bytes(value)
    return value


def _metrics(evaluation: Mapping[str, Any]) -> dict[str, dict[str, int | None]]:
    return claim_metrics(evaluation, control_delta_metric=_DELTA, control_pvalue_metric=_PVALUE, include_opposite_sign=False)


def build_measurement(*, executable_id: str, job_id: str, job_hash: str, evaluation_artifact_hash: str, evaluation: Mapping[str, Any], mission_id: str) -> dict[str, object]:
    value = {"claims": list(PLANNED_CLAIMS), "evidence_depth": EVIDENCE_DEPTH, "evidence_modes": list(EVIDENCE_MODES), "evaluation_artifact_hash": evaluation_artifact_hash, "executable_id": executable_id, "job_hash": job_hash, "job_id": job_id, "metrics": _metrics(evaluation), "mission_id": mission_id, "schema": SCIENTIFIC_MEASUREMENT_SCHEMA}
    canonical_bytes(value)
    return value


def build_result_manifest(*, executable_id: str, job_id: str, job_hash: str, measurement_artifact_hash: str, mission_id: str) -> dict[str, object]:
    value = {"evidence_depth": EVIDENCE_DEPTH, "executable_id": executable_id, "job_hash": job_hash, "job_id": job_id, "mission_id": mission_id, "observations": [{"claim_id": claim, "measurement_artifact_hash": measurement_artifact_hash} for claim in PLANNED_CLAIMS], "schema": SCIENTIFIC_RESULT_SCHEMA}
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class SessionDensePositiveSleeveJobPacket:
    output_manifest: tuple[tuple[str, str], ...]
    verdict: str

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def _load(writer: StateWriter, inputs: tuple[str, ...]) -> tuple[dict[str, Any], str, str]:
    surface = None
    manifest = None
    for artifact_hash in inputs:
        try:
            artifact = writer.evidence.verify(artifact_hash)
            value = parse_canonical((writer.evidence._root / artifact.relative_path).read_bytes())
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema") == "session_dense_positive_sleeve_surface.v1":
            surface = (value, artifact_hash)
        if isinstance(value, dict) and value.get("schema") == "session_dense_positive_sleeve_surface_manifest.v1":
            manifest = (value, artifact_hash)
    if surface is None or manifest is None or manifest[0].get("surface_artifact_hash") != surface[1]:
        raise ValueError("session dense positive surface missing")
    return surface[0], surface[1], manifest[1]


def execute_session_dense_positive_sleeve_job(*, repository_root: str | Path, execution: RunningJobExecution) -> SessionDensePositiveSleeveJobPacket:
    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(execution, expected_callable_identity=CALLABLE_IDENTITY)
    spec = binding["spec"]
    subject = spec.get("evidence_subject")
    mission_id, study_id = binding.get("mission_id"), binding.get("study_id")
    if not isinstance(mission_id, str) or not isinstance(study_id, str) or not isinstance(subject, dict) or subject.get("id") not in executable_configuration_map():
        raise ValueError("session dense positive binding invalid")
    executable_id = subject["id"]
    plan = build_session_dense_positive_sleeve_validation_plan(executable_id, mission_id=mission_id)
    plan_hash = sha256(canonical_bytes(plan)).hexdigest()
    names = output_names(executable_id, study_id=study_id)
    inputs = tuple(spec["input_hashes"])
    required = {DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, plan_hash, session_dense_positive_sleeve_chassis_implementation_sha256(), session_dense_positive_sleeve_discovery_implementation_sha256(), loader_implementation_sha256(), discovery_implementation_sha256()}
    if not required.issubset(inputs):
        raise ValueError("session dense positive inputs missing")
    produces = surface_output_name(study_id=study_id) in set(spec["expected_outputs"])
    if produces:
        surface = compute_registered_session_dense_positive_sleeve_surface(root)
        surface_hash = writer.evidence.finalize(canonical_bytes(surface)).sha256
        manifest_value = {"schema": "session_dense_positive_sleeve_surface_manifest.v1", "surface_artifact_hash": surface_hash, "surface_implementation_sha256": session_dense_positive_sleeve_discovery_implementation_sha256()}
        manifest_hash = writer.evidence.finalize(canonical_bytes(manifest_value)).sha256
    else:
        surface, surface_hash, manifest_hash = _load(writer, inputs)
    evaluation = project_session_dense_positive_sleeve_evaluation(surface, job_execution={**execution.payload(), "identity": execution.identity}, subject_executable_id=executable_id, surface_artifact_hash=surface_hash, surface_manifest_hash=manifest_hash)
    evaluation_hash = writer.evidence.finalize(canonical_bytes(evaluation)).sha256
    measurement = build_measurement(executable_id=executable_id, job_id=execution.job_id, job_hash=execution.job_hash, evaluation_artifact_hash=evaluation_hash, evaluation=evaluation, mission_id=mission_id)
    measurement_hash = writer.evidence.finalize(canonical_bytes(measurement)).sha256
    result = build_result_manifest(executable_id=executable_id, job_id=execution.job_id, job_hash=execution.job_hash, measurement_artifact_hash=measurement_hash, mission_id=mission_id)
    outputs = {names["context"]: evaluation_hash, names["environment"]: writer.evidence.finalize(canonical_bytes(build_environment_manifest())).sha256, names["measurement"]: measurement_hash, names["plan"]: writer.evidence.finalize(canonical_bytes(plan)).sha256, names["result"]: writer.evidence.finalize(canonical_bytes(result)).sha256}
    if produces:
        outputs[surface_output_name(study_id=study_id)] = surface_hash
        outputs[surface_manifest_output_name(study_id=study_id)] = manifest_hash
    return SessionDensePositiveSleeveJobPacket(tuple(sorted(outputs.items())), planned_verdict(plan, measurement))


__all__ = ["CALLABLE_IDENTITY", "CRITERIA", "EVIDENCE_DEPTH", "EVIDENCE_MODES", "PLANNED_CLAIMS", "build_environment_manifest", "build_session_dense_positive_sleeve_validation_plan", "execute_session_dense_positive_sleeve_job", "output_names", "surface_manifest_output_name", "surface_output_name"]
