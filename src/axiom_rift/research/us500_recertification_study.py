"""Journal-bound Jobs for US500 stale-receipt recertification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research.sources import SourceTransitionEvidence
from axiom_rift.research.us500_recertification import (
    build_drift_measurement,
    build_recertification_measurement,
    source_recertification_plan_hash,
)
from axiom_rift.research.us500_recertification_validation import (
    US500_RECERTIFICATION_VALIDATOR_ID,
)
from axiom_rift.research.us500_source import probe_us500_runtime, us500_source_contract


DRIFT_CALLABLE_IDENTITY = (
    "axiom_rift.research.us500_recertification_study.execute_us500_drift_job.v1"
)
RECERTIFICATION_CALLABLE_IDENTITY = (
    "axiom_rift.research.us500_recertification_study.execute_us500_recertification_job.v1"
)
_THIS_FILE = Path(__file__).resolve()


def us500_recertification_study_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def output_names(transition_evidence: str) -> dict[str, str]:
    if transition_evidence == SourceTransitionEvidence.DRIFT.value:
        return {
            "measurement": "source/us500/drift-measurement.json",
            "result": "source/us500/drift-result.json",
        }
    if transition_evidence == SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION.value:
        return {
            "measurement": "source/us500/recertification-measurement.json",
            "result": "source/us500/recertification-result.json",
        }
    raise ValueError("US500 recertification transition is not registered")


@dataclass(frozen=True, slots=True)
class SourceJobPacket:
    output_manifest: tuple[tuple[str, str], ...]

    def completion_output_manifest(self) -> dict[str, str]:
        return dict(self.output_manifest)


def _build_result(
    *,
    execution: RunningJobExecution,
    mission_id: str,
    transition_evidence: str,
    observed_at_utc: str,
    facts: Mapping[str, object],
    measurement_hash: str,
) -> dict[str, object]:
    return {
        "schema": "source_eligibility_evidence.v1",
        "job_id": execution.job_id,
        "job_hash": execution.job_hash,
        "mission_id": mission_id,
        "source_contract_id": us500_source_contract().source_contract_id,
        "transition_evidence": transition_evidence,
        "observed_at_utc": observed_at_utc,
        "facts": dict(facts),
        "measurement_artifact_hashes": [measurement_hash],
    }


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
    source_id = us500_source_contract().source_contract_id
    if (
        not isinstance(binding.get("mission_id"), str)
        or not isinstance(binding.get("study_id"), str)
        or binding["spec"].get("evidence_subject")
        != {"kind": "Study", "id": binding["study_id"]}
        or not isinstance(source_binding, dict)
        or source_binding.get("source_contract_id") != source_id
        or source_binding.get("transition_evidence") != transition_evidence
        or source_binding.get("validation_plan_hash")
        != source_recertification_plan_hash(transition_evidence)
        or source_binding.get("validator_id") != US500_RECERTIFICATION_VALIDATOR_ID
        or source_binding.get("result_manifest_output") != names["result"]
    ):
        raise ValueError("running Job is not bound to the US500 recertification edge")
    with writer._open_authoritative_index() as index:
        head = index.event_head(f"source:{source_id}")
        state = None if head is None else index.get(head.record_kind, head.record_id)
    if state is None:
        raise ValueError("current US500 source state is absent")
    if transition_evidence == SourceTransitionEvidence.DRIFT.value:
        observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
        measurement = build_drift_measurement(
            source_state_record_id=state.record_id,
            source_state_status=state.status,
            source_state_payload=state.payload,
            observed_at_utc=observed_at,
        )
    else:
        probe = probe_us500_runtime(root)
        measurement = build_recertification_measurement(
            source_state_record_id=state.record_id,
            source_state_status=state.status,
            source_state_payload=state.payload,
            runtime_probe=probe,
        )
        observed_at = measurement["observed_at_utc"]
    measurement_hash = writer.evidence.finalize(canonical_bytes(measurement)).sha256
    result = _build_result(
        execution=execution,
        mission_id=binding["mission_id"],
        transition_evidence=transition_evidence,
        observed_at_utc=observed_at,
        facts=measurement["facts"],
        measurement_hash=measurement_hash,
    )
    result_hash = writer.evidence.finalize(canonical_bytes(result)).sha256
    return SourceJobPacket(
        output_manifest=tuple(
            sorted(
                {
                    names["measurement"]: measurement_hash,
                    names["result"]: result_hash,
                }.items()
            )
        )
    )


def execute_us500_drift_job(
    *, repository_root: str | Path, execution: RunningJobExecution
) -> SourceJobPacket:
    return _execute(
        repository_root=repository_root,
        execution=execution,
        transition_evidence=SourceTransitionEvidence.DRIFT.value,
        callable_identity=DRIFT_CALLABLE_IDENTITY,
    )


def execute_us500_recertification_job(
    *, repository_root: str | Path, execution: RunningJobExecution
) -> SourceJobPacket:
    return _execute(
        repository_root=repository_root,
        execution=execution,
        transition_evidence=SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION.value,
        callable_identity=RECERTIFICATION_CALLABLE_IDENTITY,
    )


__all__ = [
    "DRIFT_CALLABLE_IDENTITY",
    "RECERTIFICATION_CALLABLE_IDENTITY",
    "SourceJobPacket",
    "execute_us500_drift_job",
    "execute_us500_recertification_job",
    "output_names",
    "us500_recertification_study_implementation_sha256",
]
