"""Running-Job boundary for the prospective sleeve loss-skip Study."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.running_job_context import RunningJobExecutionContext
from axiom_rift.research.prospective_pair_trace import (
    build_prospective_pair_calculation,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (
    executable_configuration_map,
)
from axiom_rift.research.sleeve_loss_skip_risk_study import (
    SleeveLossSkipRiskJobPacket,
    build_environment_manifest,
    build_measurement,
    build_result,
    build_sleeve_loss_skip_risk_job_plan,
)
from axiom_rift.research.sleeve_loss_skip_risk_trace import (
    compute_sleeve_loss_skip_risk_trace,
)
from axiom_rift.research.validation_v2 import (
    adjudicate_validation_measurement_v2,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.sleeve_loss_skip_risk_runtime."
    "execute_sleeve_loss_skip_risk_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = "python.source.sleeve_loss_skip_risk.v1"
_THIS_FILE = Path(__file__).resolve()


def sleeve_loss_skip_risk_runtime_path() -> Path:
    return _THIS_FILE


def execute_sleeve_loss_skip_risk_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> SleeveLossSkipRiskJobPacket:
    root = Path(repository_root).resolve()
    writer = RunningJobExecutionContext(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    subject = binding.get("spec", {}).get("evidence_subject")
    mission_id = binding.get("mission_id")
    study_id = binding.get("study_id")
    if (
        not isinstance(subject, Mapping)
        or subject.get("id") not in executable_configuration_map()
        or type(mission_id) is not str
        or type(study_id) is not str
    ):
        raise ValueError("sleeve loss-skip running Job binding is invalid")
    scoped = build_sleeve_loss_skip_risk_job_plan(
        repository_root=root,
        mission_id=mission_id,
        study_id=study_id,
        executable_id=str(subject["id"]),
    )
    spec = binding["spec"]
    if set(spec["expected_outputs"]) != set(scoped.expected_outputs()):
        raise ValueError("sleeve loss-skip Job output registration drifted")
    if not set(scoped.job_input_hashes()).issubset(set(spec["input_hashes"])):
        raise ValueError("sleeve loss-skip Job inputs are incomplete")
    trace = compute_sleeve_loss_skip_risk_trace(
        root,
        definition=scoped.definition,
        mission_id=mission_id,
        subject_executable_id=scoped.executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
    )
    names = scoped.output_names
    trace_hash = writer.evidence.finalize(canonical_bytes(trace)).sha256
    calculation = build_prospective_pair_calculation(
        trace=trace,
        trace_output_name=names["trace"],
        definition=scoped.definition,
    )
    calculation_hash = writer.evidence.finalize(
        canonical_bytes(calculation)
    ).sha256
    measurement = build_measurement(
        scoped_plan=scoped,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        calculation=calculation,
        trace_sha256=trace_hash,
        calculation_sha256=calculation_hash,
    )
    measurement_hash = writer.evidence.finalize(
        canonical_bytes(measurement)
    ).sha256
    result = build_result(
        scoped_plan=scoped,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_sha256=measurement_hash,
    )
    outputs = {
        names["calculation"]: calculation_hash,
        names["environment"]: writer.evidence.finalize(
            canonical_bytes(build_environment_manifest())
        ).sha256,
        names["measurement"]: measurement_hash,
        names["plan"]: writer.evidence.finalize(
            canonical_bytes(scoped.plan)
        ).sha256,
        names["result"]: writer.evidence.finalize(
            canonical_bytes(result)
        ).sha256,
        names["trace"]: trace_hash,
    }
    adjudication = adjudicate_validation_measurement_v2(scoped.plan, measurement)
    return SleeveLossSkipRiskJobPacket(
        adjudication_state=adjudication.state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "CALLABLE_IDENTITY",
    "JOB_IMPLEMENTATION_PROTOCOL",
    "execute_sleeve_loss_skip_risk_job",
    "sleeve_loss_skip_risk_runtime_path",
]
