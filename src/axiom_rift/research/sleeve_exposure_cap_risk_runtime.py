"""Running-Job boundary for the prospective sleeve exposure-cap Study."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.running_job_context import RunningJobExecutionContext
from axiom_rift.research.prospective_pair_trace import (
    build_prospective_pair_calculation,
    prospective_pair_protocol_definition_from_manifest,
)
from axiom_rift.research.sleeve_exposure_cap_risk_cache import (
    build_sleeve_exposure_cap_risk_cache_provenance,
    materialize_sleeve_exposure_cap_risk_cache,
    sleeve_exposure_cap_risk_family_cache,
    verify_sleeve_exposure_cap_risk_cache_producer,
)
from axiom_rift.research.sleeve_exposure_cap_risk_chassis import (
    executable_configuration_map,
)
from axiom_rift.research.sleeve_exposure_cap_risk_study import (
    SleeveExposureCapRiskJobPacket,
    build_environment_manifest,
    build_measurement,
    build_result,
    build_sleeve_exposure_cap_risk_job_plan,
)
from axiom_rift.research.sleeve_exposure_cap_risk_trace import (
    bind_sleeve_exposure_cap_risk_family_trace,
    compute_sleeve_exposure_cap_risk_family_trace,
)
from axiom_rift.research.validation_v2 import (
    adjudicate_validation_measurement_v2,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.sleeve_exposure_cap_risk_runtime."
    "execute_sleeve_exposure_cap_risk_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = "python.source.sleeve_exposure_cap_risk.v1"
_THIS_FILE = Path(__file__).resolve()


def sleeve_exposure_cap_risk_runtime_path() -> Path:
    return _THIS_FILE


def execute_sleeve_exposure_cap_risk_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> SleeveExposureCapRiskJobPacket:
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
        raise ValueError("sleeve exposure-cap running Job binding is invalid")
    spec = binding["spec"]
    scientific_binding = spec.get("scientific_binding")
    plan_hash = (
        None
        if not isinstance(scientific_binding, Mapping)
        else scientific_binding.get("validation_plan_hash")
    )
    if type(plan_hash) is not str or plan_hash not in spec.get("input_hashes", ()):
        raise ValueError("sleeve exposure-cap validation plan input is absent")
    try:
        plan_value = parse_canonical(writer.evidence.read_verified(plan_hash))
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("sleeve exposure-cap validation plan is unavailable") from exc
    if not isinstance(plan_value, Mapping):
        raise ValueError("sleeve exposure-cap validation plan is not an object")
    definition = prospective_pair_protocol_definition_from_manifest(
        plan_value.get("protocol_definition")
    )
    subject_id = str(subject["id"])
    producer_id = definition.prospective_executable_ids[0]
    scoped = build_sleeve_exposure_cap_risk_job_plan(
        repository_root=root,
        mission_id=mission_id,
        study_id=study_id,
        executable_id=subject_id,
        definition=(None if subject_id == producer_id else definition),
    )
    if (
        plan_value != scoped.plan
        or set(spec["expected_outputs"]) != set(scoped.expected_outputs())
        or spec.get("output_classes") != scoped.expected_output_classes()
    ):
        raise ValueError("sleeve exposure-cap Job registration drifted")
    input_hashes = tuple(spec.get("input_hashes", ()))
    if len(input_hashes) != len(set(input_hashes)):
        raise ValueError("sleeve exposure-cap Job inputs are duplicated")
    if scoped.produces_family_cache:
        if tuple(sorted(input_hashes)) != scoped.job_input_hashes():
            raise ValueError("sleeve exposure-cap producer inputs drifted")
        family_trace = compute_sleeve_exposure_cap_risk_family_trace(
            root,
            definition=scoped.definition,
        )
        cache = sleeve_exposure_cap_risk_family_cache(
            definition=scoped.definition,
            family_trace=family_trace,
            produced=True,
        )
        cache_artifact = writer.evidence.finalize(cache.content)
        if cache_artifact.sha256 != cache.sha256:
            raise ValueError("sleeve exposure-cap cache evidence identity drifted")
        materialize_sleeve_exposure_cap_risk_cache(
            root,
            definition=scoped.definition,
            content=cache.content,
        )
    else:
        producer_plan = build_sleeve_exposure_cap_risk_job_plan(
            repository_root=root,
            mission_id=mission_id,
            study_id=study_id,
            executable_id=producer_id,
            definition=scoped.definition,
        )
        cache, provenance_hash, producer_trace_hash, provenance = (
            verify_sleeve_exposure_cap_risk_cache_producer(
                writer,
                repository_root=root,
                input_hashes=input_hashes,
                definition=scoped.definition,
                mission_id=mission_id,
                study_id=study_id,
                producer_executable_id=producer_id,
                producer_trace_output_name=producer_plan.output_names["trace"],
                producer_expected_output_classes=(
                    producer_plan.expected_output_classes()
                ),
                expected_callable_identity=CALLABLE_IDENTITY,
            )
        )
        expected_inputs = scoped.job_input_hashes(
            cache_sha256=cache.sha256,
            cache_provenance_sha256=provenance_hash,
            producer_trace_sha256=producer_trace_hash,
        )
        if tuple(sorted(input_hashes)) != expected_inputs:
            raise ValueError("sleeve exposure-cap consumer inputs drifted")
        if provenance.get("cache_sha256") != cache.sha256:
            raise ValueError("sleeve exposure-cap cache provenance drifted")
    trace = bind_sleeve_exposure_cap_risk_family_trace(
        cache.trace(scoped.definition),
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
    if scoped.produces_family_cache:
        provenance = build_sleeve_exposure_cap_risk_cache_provenance(
            definition=scoped.definition,
            mission_id=mission_id,
            study_id=study_id,
            producer_executable_id=scoped.executable_id,
            producer_trace_output_name=names["trace"],
            execution=execution,
            cache_sha256=cache.sha256,
            producer_trace_sha256=trace_hash,
        )
        outputs[scoped.cache_output_name] = cache.sha256
        outputs[scoped.cache_provenance_output_name] = (
            writer.evidence.finalize(canonical_bytes(provenance)).sha256
        )
    if set(outputs) != set(scoped.expected_outputs()):
        raise ValueError("sleeve exposure-cap Job emitted undeclared outputs")
    adjudication = adjudicate_validation_measurement_v2(scoped.plan, measurement)
    return SleeveExposureCapRiskJobPacket(
        adjudication_state=adjudication.state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "CALLABLE_IDENTITY",
    "JOB_IMPLEMENTATION_PROTOCOL",
    "execute_sleeve_exposure_cap_risk_job",
    "sleeve_exposure_cap_risk_runtime_path",
]
