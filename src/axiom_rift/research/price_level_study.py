"""Evidence plan and writer-gated Job for price-level interaction discovery."""

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
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.operations import writer as writer_module
from axiom_rift.research.discovery import DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, discovery_implementation_sha256
from axiom_rift.research.price_level_discovery import (
    compute_registered_price_level_surface,
    executable_configuration_map,
    loader_implementation_sha256,
    price_level_implementation_sha256,
    project_price_level_evaluation,
)
from axiom_rift.research.trend_study import CRITERIA, EVIDENCE_MODES, PLANNED_CLAIMS, _claim_metrics, planned_verdict
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    SCIENTIFIC_MEASUREMENT_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    build_validation_plan,
)


MISSION_ID = "MIS-0002"
STUDY_ID = "STU-0022"
CALLABLE_IDENTITY = "axiom_rift.research.price_level_study.execute_price_level_job.v1"
EVIDENCE_DEPTH = "discovery"


def build_price_level_validation_plan(executable_id: str) -> dict[str, object]:
    return build_validation_plan(
        mission_id=MISSION_ID,
        executable_id=executable_id,
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=PLANNED_CLAIMS,
        evidence_modes=EVIDENCE_MODES,
        criteria=CRITERIA,
        candidate_eligible_on_pass=False,
    )


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


def surface_output_name() -> str:
    return f"scientific/{STUDY_ID}/price-level-surface.json"


def surface_manifest_output_name() -> str:
    return f"scientific/{STUDY_ID}/price-level-surface-manifest.json"


def build_environment_manifest() -> dict[str, object]:
    value: dict[str, object] = {
        "dataset_sha256": DATASET_SHA256,
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "price_level_implementation_sha256": price_level_implementation_sha256(),
        "python_version": ".".join(str(item) for item in sys.version_info[:3]),
        "runner_implementation_sha256": sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
        "schema": "scientific_engine_environment.v1",
        "scipy_version": scipy.__version__,
        "shared_discovery_implementation_sha256": discovery_implementation_sha256(),
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
        "writer_implementation_sha256": sha256(Path(writer_module.__file__).resolve().read_bytes()).hexdigest(),
    }
    canonical_bytes(value)
    return value


def build_measurement(*, executable_id: str, job_id: str, job_hash: str, evaluation_artifact_hash: str, evaluation: Mapping[str, Any]) -> dict[str, object]:
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


def build_result_manifest(*, executable_id: str, job_id: str, job_hash: str, measurement_artifact_hash: str) -> dict[str, object]:
    value: dict[str, object] = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": MISSION_ID,
        "observations": [
            {"claim_id": claim, "measurement_artifact_hash": measurement_artifact_hash}
            for claim in PLANNED_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class PriceLevelJobPacket:
    output_manifest: tuple[tuple[str, str], ...]
    verdict: str

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def _load_surface_from_inputs(writer: StateWriter, input_hashes: tuple[str, ...]) -> tuple[dict[str, Any], str, str]:
    surface: tuple[dict[str, Any], str] | None = None
    manifest: tuple[dict[str, Any], str] | None = None
    for artifact_hash in input_hashes:
        try:
            artifact = writer.evidence.verify(artifact_hash)
            value = parse_canonical((writer.evidence._root / artifact.relative_path).read_bytes())
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema") == "price_level_discovery_surface.v1":
            surface = (value, artifact_hash)
        if isinstance(value, dict) and value.get("schema") == "price_level_surface_manifest.v1":
            manifest = (value, artifact_hash)
    if surface is None or manifest is None or manifest[0].get("surface_artifact_hash") != surface[1]:
        raise ValueError("price-level Job inputs lack one bound surface and manifest")
    return surface[0], surface[1], manifest[1]


def execute_price_level_job(*, repository_root: str | Path, execution: RunningJobExecution) -> PriceLevelJobPacket:
    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(execution, expected_callable_identity=CALLABLE_IDENTITY)
    spec = binding["spec"]
    subject = spec.get("evidence_subject")
    if binding.get("mission_id") != MISSION_ID or binding.get("study_id") != STUDY_ID or not isinstance(subject, dict) or subject.get("kind") != "Executable" or subject.get("id") not in executable_configuration_map():
        raise ValueError("running Job is not bound to the price-level Study")
    executable_id = subject["id"]
    plan = build_price_level_validation_plan(executable_id)
    environment = build_environment_manifest()
    plan_hash = sha256(canonical_bytes(plan)).hexdigest()
    scientific_binding = spec.get("scientific_binding")
    names = output_names(executable_id)
    if not isinstance(scientific_binding, dict) or scientific_binding.get("validator_id") != SCIENTIFIC_DISCOVERY_VALIDATOR_ID or scientific_binding.get("validation_plan_hash") != plan_hash or scientific_binding.get("result_manifest_output") != names["result"]:
        raise ValueError("price-level scientific binding differs from preregistration")
    inputs = tuple(spec.get("input_hashes", []))
    if not {DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, plan_hash, price_level_implementation_sha256(), loader_implementation_sha256(), discovery_implementation_sha256()}.issubset(inputs):
        raise ValueError("price-level Job omits a required content-bound input")
    expected_outputs = set(spec.get("expected_outputs", []))
    subject_outputs = set(names.values())
    produces_surface = surface_output_name() in expected_outputs
    expected = subject_outputs | ({surface_output_name(), surface_manifest_output_name()} if produces_surface else set())
    if expected_outputs != expected or any(spec["output_classes"].get(name) != "durable_evidence" for name in expected):
        raise ValueError("price-level Job outputs differ from protocol")
    if produces_surface:
        surface = compute_registered_price_level_surface(root)
        surface_bytes = canonical_bytes(surface)
        surface_hash = writer.evidence.finalize(surface_bytes).sha256
        manifest_value = {
            "producer_execution": {**execution.payload(), "identity": execution.identity},
            "schema": "price_level_surface_manifest.v1",
            "surface_artifact_hash": surface_hash,
            "surface_implementation_sha256": price_level_implementation_sha256(),
        }
        manifest_hash = writer.evidence.finalize(canonical_bytes(manifest_value)).sha256
    else:
        surface, surface_hash, manifest_hash = _load_surface_from_inputs(writer, inputs)
    evaluation = project_price_level_evaluation(surface, job_execution={**execution.payload(), "identity": execution.identity}, subject_executable_id=executable_id, surface_artifact_hash=surface_hash, surface_manifest_hash=manifest_hash)
    evaluation_hash = writer.evidence.finalize(canonical_bytes(evaluation)).sha256
    measurement = build_measurement(executable_id=executable_id, job_id=execution.job_id, job_hash=execution.job_hash, evaluation_artifact_hash=evaluation_hash, evaluation=evaluation)
    measurement_hash = writer.evidence.finalize(canonical_bytes(measurement)).sha256
    result = build_result_manifest(executable_id=executable_id, job_id=execution.job_id, job_hash=execution.job_hash, measurement_artifact_hash=measurement_hash)
    outputs = {
        names["context"]: evaluation_hash,
        names["environment"]: writer.evidence.finalize(canonical_bytes(environment)).sha256,
        names["measurement"]: measurement_hash,
        names["plan"]: writer.evidence.finalize(canonical_bytes(plan)).sha256,
        names["result"]: writer.evidence.finalize(canonical_bytes(result)).sha256,
    }
    if produces_surface:
        outputs[surface_output_name()] = surface_hash
        outputs[surface_manifest_output_name()] = manifest_hash
    if set(outputs) != expected_outputs:
        raise ValueError("price-level materialized outputs differ from declaration")
    return PriceLevelJobPacket(output_manifest=tuple(sorted(outputs.items())), verdict=planned_verdict(plan, measurement))


__all__ = [
    "CALLABLE_IDENTITY",
    "EVIDENCE_DEPTH",
    "EVIDENCE_MODES",
    "MISSION_ID",
    "PLANNED_CLAIMS",
    "STUDY_ID",
    "PriceLevelJobPacket",
    "build_environment_manifest",
    "build_measurement",
    "build_price_level_validation_plan",
    "build_result_manifest",
    "execute_price_level_job",
    "output_names",
    "surface_manifest_output_name",
    "surface_output_name",
]
