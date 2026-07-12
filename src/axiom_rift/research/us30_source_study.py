"""Journal-bound source eligibility Jobs for FPMarkets US30 M5."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research import us30_source_eligibility_validation as validator_module
from axiom_rift.research import us30_source as source_module
from axiom_rift.research.us30_source_eligibility_validation import (
    SOURCE_ELIGIBILITY_VALIDATOR_ID,
)
from axiom_rift.research.us30_source import (
    build_us30_historical_audit,
    probe_us30_runtime,
    source_validation_plan_hash,
    us30_source_contract,
)


HISTORICAL_CALLABLE_IDENTITY = (
    "axiom_rift.research.us30_source_study.execute_us30_historical_audit_job.v2"
)
RUNTIME_CALLABLE_IDENTITY = (
    "axiom_rift.research.us30_source_study.execute_us30_runtime_availability_job.v2"
)
_THIS_FILE = Path(__file__).resolve()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def source_study_implementation_sha256() -> str:
    return _file_sha256(_THIS_FILE)


def source_dependency_sha256() -> str:
    return _file_sha256(Path(source_module.__file__).resolve())


def source_validator_implementation_sha256() -> str:
    return _file_sha256(Path(validator_module.__file__).resolve())


def output_names(transition_evidence: str) -> dict[str, str]:
    if transition_evidence == "historical_audit":
        return {
            "raw": "source/us30/historical.csv",
            "measurement": "source/us30/historical-audit.json",
            "result": "source/us30/historical-result.json",
        }
    if transition_evidence == "runtime_availability_proof":
        return {
            "measurement": "source/us30/runtime-probe.json",
            "result": "source/us30/runtime-result.json",
        }
    raise ValueError("source transition is not registered")


@dataclass(frozen=True, slots=True)
class SourceJobPacket:
    artifacts: tuple[tuple[str, bytes], ...]
    output_manifest: tuple[tuple[str, str], ...]
    transition_evidence: str

    def artifact(self, role: str) -> bytes:
        return dict(self.artifacts)[role]

    def completion_output_manifest(self) -> dict[str, str]:
        return dict(self.output_manifest)


def _build_result(
    *,
    execution: RunningJobExecution,
    transition_evidence: str,
    observed_at_utc: str,
    facts: Mapping[str, Any],
    measurement_hashes: tuple[str, ...],
    mission_id: str,
) -> dict[str, Any]:
    result = {
        "schema": "source_eligibility_evidence.v1",
        "job_id": execution.job_id,
        "job_hash": execution.job_hash,
        "mission_id": mission_id,
        "source_contract_id": us30_source_contract().source_contract_id,
        "transition_evidence": transition_evidence,
        "observed_at_utc": observed_at_utc,
        "facts": dict(facts),
        "measurement_artifact_hashes": sorted(measurement_hashes),
    }
    canonical_bytes(result)
    return result


def _execute(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
    transition_evidence: str,
    callable_identity: str,
) -> SourceJobPacket:
    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=callable_identity,
    )
    source_binding = binding["spec"].get("source_binding")
    names = output_names(transition_evidence)
    contract_id = us30_source_contract().source_contract_id
    plan_hash = source_validation_plan_hash(transition_evidence)
    if (
        not isinstance(binding.get("mission_id"), str)
        or not isinstance(binding.get("study_id"), str)
        or binding["spec"].get("evidence_subject")
        != {"kind": "Study", "id": binding["study_id"]}
        or not isinstance(source_binding, dict)
        or source_binding.get("source_contract_id") != contract_id
        or source_binding.get("transition_evidence") != transition_evidence
        or source_binding.get("validation_plan_hash") != plan_hash
        or source_binding.get("validator_id") != SOURCE_ELIGIBILITY_VALIDATOR_ID
        or source_binding.get("result_manifest_output") != names["result"]
    ):
        raise ValueError("running Job is not bound to the registered US30 source transition")
    spec = binding["spec"]
    required_inputs = {
        contract_id.removeprefix("source:"),
        plan_hash,
        source_study_implementation_sha256(),
        source_dependency_sha256(),
        source_validator_implementation_sha256(),
    }
    if not required_inputs.issubset(spec.get("input_hashes", [])):
        raise ValueError("US30 source Job omits a required content-bound input")
    expected_outputs = set(names.values())
    if (
        set(spec.get("expected_outputs", [])) != expected_outputs
        or spec.get("output_classes")
        != {name: "durable_evidence" for name in expected_outputs}
    ):
        raise ValueError("US30 source Job outputs differ from registration")

    artifact_bytes: dict[str, bytes]
    if transition_evidence == "historical_audit":
        raw, measurement = build_us30_historical_audit(root)
        artifact_bytes = {
            "raw": raw,
            "measurement": canonical_bytes(measurement),
        }
        facts = measurement["facts"]
        observed_at = measurement["observed_at_utc"]
    else:
        measurement = probe_us30_runtime(root)
        artifact_bytes = {"measurement": canonical_bytes(measurement)}
        facts = measurement["facts"]
        observed_at = measurement["observed_at_utc"]
    output_manifest = {
        names[role]: writer.evidence.finalize(content).sha256
        for role, content in artifact_bytes.items()
    }
    measurement_hashes = tuple(sorted(output_manifest.values()))
    result = _build_result(
        execution=execution,
        transition_evidence=transition_evidence,
        observed_at_utc=observed_at,
        facts=facts,
        measurement_hashes=measurement_hashes,
        mission_id=binding["mission_id"],
    )
    result_bytes = canonical_bytes(result)
    output_manifest[names["result"]] = writer.evidence.finalize(result_bytes).sha256
    artifact_bytes["result"] = result_bytes
    if set(output_manifest) != expected_outputs:
        raise ValueError("US30 source materialization differs from declaration")
    return SourceJobPacket(
        artifacts=tuple(sorted(artifact_bytes.items())),
        output_manifest=tuple(sorted(output_manifest.items())),
        transition_evidence=transition_evidence,
    )


def execute_us30_historical_audit_job(
    *, repository_root: str | Path, execution: RunningJobExecution
) -> SourceJobPacket:
    return _execute(
        repository_root=repository_root,
        execution=execution,
        transition_evidence="historical_audit",
        callable_identity=HISTORICAL_CALLABLE_IDENTITY,
    )


def execute_us30_runtime_availability_job(
    *, repository_root: str | Path, execution: RunningJobExecution
) -> SourceJobPacket:
    return _execute(
        repository_root=repository_root,
        execution=execution,
        transition_evidence="runtime_availability_proof",
        callable_identity=RUNTIME_CALLABLE_IDENTITY,
    )


__all__ = [
    "HISTORICAL_CALLABLE_IDENTITY",
    "RUNTIME_CALLABLE_IDENTITY",
    "SOURCE_ELIGIBILITY_VALIDATOR_ID",
    "SourceJobPacket",
    "execute_us30_historical_audit_job",
    "execute_us30_runtime_availability_job",
    "output_names",
    "source_dependency_sha256",
    "source_study_implementation_sha256",
    "source_validator_implementation_sha256",
]
