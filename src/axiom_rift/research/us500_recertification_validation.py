"""Independent validator for US500 stale-receipt recertification evidence."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
)
from axiom_rift.research.sources import SourceTransitionEvidence
from axiom_rift.research.us500_recertification import (
    DRIFT_FACTS,
    RECERTIFICATION_FACTS,
    contract_from_payload,
    receipt_from_payload,
    source_recertification_plan_hash,
)
from axiom_rift.research.us500_source import derive_runtime_facts, us500_source_contract


_THIS_FILE = Path(__file__).resolve()
US500_RECERTIFICATION_VALIDATOR_ID = validator_identity(
    protocol="fpmarkets_us500_source_recertification.v1",
    domains=frozenset({"source"}),
    implementation_sha256=sha256(_THIS_FILE.read_bytes()).hexdigest(),
)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError(f"{name} is not a mapping")
    return value


class US500RecertificationValidator:
    validator_id = US500_RECERTIFICATION_VALIDATOR_ID
    domains = frozenset({"source"})
    implementation_path = _THIS_FILE
    protocol = "fpmarkets_us500_source_recertification.v1"

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if request.domain != "source" or request.validator_id != self.validator_id:
            raise EvidenceValidationError("US500 recertification validator received another domain")
        binding = _mapping(request.binding, "source binding")
        transition = binding.get("transition_evidence")
        if transition not in {
            SourceTransitionEvidence.DRIFT.value,
            SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION.value,
        }:
            raise EvidenceValidationError("US500 recertification transition is unsupported")
        source_id = us500_source_contract().source_contract_id
        if (
            binding.get("source_contract_id") != source_id
            or request.validation_plan_hash != source_recertification_plan_hash(transition)
        ):
            raise EvidenceValidationError("source contract or recertification plan differs")
        result_name = binding.get("result_manifest_output")
        artifacts = {artifact.output_name: artifact for artifact in request.artifacts}
        if not isinstance(result_name, str) or result_name not in artifacts:
            raise EvidenceValidationError("source recertification result is absent")
        contents = {name: artifact.read_bytes() for name, artifact in artifacts.items()}
        try:
            result = parse_canonical(contents[result_name])
        except ValueError as exc:
            raise EvidenceValidationError("source recertification result is not canonical") from exc
        result = _mapping(result, "source recertification result")
        required_result = {
            "facts",
            "job_hash",
            "job_id",
            "measurement_artifact_hashes",
            "mission_id",
            "observed_at_utc",
            "schema",
            "source_contract_id",
            "transition_evidence",
        }
        if (
            set(result) != required_result
            or result.get("schema") != "source_eligibility_evidence.v1"
            or result.get("job_id") != request.job_id
            or result.get("job_hash") != request.job_hash
            or result.get("mission_id") != request.mission_id
            or result.get("source_contract_id") != source_id
            or result.get("transition_evidence") != transition
        ):
            raise EvidenceValidationError("source recertification result provenance is invalid")
        measurement_names = [name for name in artifacts if name != result_name]
        if len(measurement_names) != 1 or not measurement_names[0].endswith(".json"):
            raise EvidenceValidationError("source recertification measurement is not exact")
        measurement_hashes = tuple(sorted(artifacts[name].sha256 for name in measurement_names))
        if tuple(sorted(result.get("measurement_artifact_hashes", ()))) != measurement_hashes:
            raise EvidenceValidationError("source recertification measurement hashes differ")
        try:
            measurement = parse_canonical(contents[measurement_names[0]])
        except ValueError as exc:
            raise EvidenceValidationError("source recertification measurement is not canonical") from exc
        measurement = _mapping(measurement, "source recertification measurement")
        contract = contract_from_payload(_mapping(measurement.get("contract"), "source contract"))
        receipt = receipt_from_payload(_mapping(measurement.get("receipt"), "source receipt"))
        observed_at = measurement.get("observed_at_utc")
        if (
            contract.identity != source_id
            or contract.to_identity_payload() != measurement.get("contract")
            or receipt.identity != measurement.get("eligibility_receipt_id")
            or measurement.get("source_contract_id") != source_id
            or not isinstance(observed_at, str)
            or result.get("observed_at_utc") != observed_at
        ):
            raise EvidenceValidationError("source state identity is invalid")
        if transition == SourceTransitionEvidence.DRIFT.value:
            expected_fields = set(
                [
                    "contract",
                    "eligibility_receipt_id",
                    "facts",
                    "observed_at_utc",
                    "receipt",
                    "receipt_age_seconds",
                    "schema",
                    "source_contract_id",
                    "source_state_record_id",
                    "source_state_status",
                ]
            )
            if (
                set(measurement) != expected_fields
                or measurement.get("schema") != "us500_source_drift_measurement.v1"
                or measurement.get("source_state_status") != "runtime_eligible"
                or receipt.evidence is not SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF
            ):
                raise EvidenceValidationError("source drift measurement schema is invalid")
            from datetime import datetime, timezone

            current = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
            prior = datetime.fromisoformat(receipt.observed_at_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
            age_seconds = int((current - prior).total_seconds())
            ttl_seconds = contract.availability().get(
                "eligibility_receipt_ttl_seconds",
                contract.availability()["causal_ttl_seconds"],
            )
            if (
                measurement.get("receipt_age_seconds") != age_seconds
                or isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, int)
                or age_seconds <= ttl_seconds
            ):
                raise EvidenceValidationError("source drift does not prove a stale receipt")
            facts = dict(DRIFT_FACTS)
        else:
            expected_fields = set(
                [
                    "contract",
                    "eligibility_receipt_id",
                    "facts",
                    "observed_at_utc",
                    "receipt",
                    "runtime_probe",
                    "schema",
                    "source_contract_id",
                    "source_state_record_id",
                    "source_state_status",
                ]
            )
            probe = _mapping(measurement.get("runtime_probe"), "runtime probe")
            proposed = us500_source_contract()
            runtime_facts = derive_runtime_facts(probe)
            if (
                set(measurement) != expected_fields
                or measurement.get("schema") != "us500_source_recertification_measurement.v1"
                or measurement.get("source_state_status") != "suspended"
                or receipt.evidence is not SourceTransitionEvidence.DRIFT
                or probe.get("source_contract_id") != source_id
                or probe.get("observed_at_utc") != observed_at
                or any(
                    runtime_facts[name] is not True
                    for name in runtime_facts
                    if name != "latency_ms"
                )
                or contract.to_identity_payload() != proposed.to_identity_payload()
            ):
                raise EvidenceValidationError("same-semantics recertification did not pass")
            facts = dict(RECERTIFICATION_FACTS)
        if canonical_bytes(measurement.get("facts")) != canonical_bytes(facts):
            raise EvidenceValidationError("source recertification facts were not derived")
        if canonical_bytes(result.get("facts")) != canonical_bytes(facts):
            raise EvidenceValidationError("source result facts differ from measurement")
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=measurement_hashes,
            facts={**facts, "observed_at_utc": observed_at},
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "US500_RECERTIFICATION_VALIDATOR_ID",
    "US500RecertificationValidator",
]
