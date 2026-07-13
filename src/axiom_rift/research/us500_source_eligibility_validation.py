
"""Independent validator for FPMarkets US500 source eligibility evidence."""

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
from axiom_rift.research.us500_source import (
    HISTORICAL_FACT_FIELDS,
    RUNTIME_FACT_FIELDS,
    audit_us500_historical_bytes,
    derive_runtime_facts,
    source_validation_plan_hash,
    us500_source_contract,
)


_THIS_FILE = Path(__file__).resolve()
_EXPECTED_RAW_SHA256 = (
    "6d638467069a756a7a3897b587ec16a4b9ff76df8718186c2a81905d6d0488d4"
)
SOURCE_ELIGIBILITY_VALIDATOR_ID = validator_identity(
    protocol="fpmarkets_us500_source_eligibility.v1",
    domains=frozenset({"source"}),
    implementation_sha256=sha256(_THIS_FILE.read_bytes()).hexdigest(),
)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError(f"{name} is not a mapping")
    return value


class SourceEligibilityValidator:
    """Derive source facts from declared bytes; never authorize science."""

    validator_id = SOURCE_ELIGIBILITY_VALIDATOR_ID
    domains = frozenset({"source"})
    implementation_path = _THIS_FILE
    protocol = "fpmarkets_us500_source_eligibility.v1"

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if request.domain != "source" or request.validator_id != self.validator_id:
            raise EvidenceValidationError("US500 validator received another domain")
        binding = _mapping(request.binding, "source binding")
        transition = binding.get("transition_evidence")
        if transition not in {"historical_audit", "runtime_availability_proof"}:
            raise EvidenceValidationError("source transition is not supported")
        source_id = us500_source_contract().source_contract_id
        if (
            binding.get("source_contract_id") != source_id
            or request.validation_plan_hash != source_validation_plan_hash(transition)
        ):
            raise EvidenceValidationError("source contract or validation plan differs")
        result_name = binding.get("result_manifest_output")
        artifacts = {artifact.output_name: artifact for artifact in request.artifacts}
        if not isinstance(result_name, str) or result_name not in artifacts:
            raise EvidenceValidationError("source result artifact is absent")
        contents = {
            name: artifact.read_bytes()
            for name, artifact in artifacts.items()
        }
        try:
            result = parse_canonical(contents[result_name])
        except ValueError as exc:
            raise EvidenceValidationError("source result is not canonical") from exc
        result = _mapping(result, "source result")
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
            raise EvidenceValidationError("source result provenance is invalid")
        measurement_names = [name for name in artifacts if name != result_name]
        measurement_hashes = tuple(sorted(artifacts[name].sha256 for name in measurement_names))
        observed_hashes = result.get("measurement_artifact_hashes")
        if not isinstance(observed_hashes, (list, tuple)) or tuple(sorted(observed_hashes)) != measurement_hashes:
            raise EvidenceValidationError("source measurement hashes differ")

        observed_at = result.get("observed_at_utc")
        if not isinstance(observed_at, str) or not observed_at.isascii():
            raise EvidenceValidationError("source observation timestamp is invalid")
        if transition == "historical_audit":
            csv_names = [name for name in measurement_names if name.endswith(".csv")]
            json_names = [name for name in measurement_names if name.endswith(".json")]
            if len(csv_names) != 1 or len(json_names) != 1:
                raise EvidenceValidationError("historical source outputs are not exact")
            try:
                measurement = parse_canonical(contents[json_names[0]])
            except ValueError as exc:
                raise EvidenceValidationError("historical audit is not canonical") from exc
            expected = audit_us500_historical_bytes(
                contents[csv_names[0]], observed_at_utc=observed_at
            )
            if expected["raw_sha256"] != _EXPECTED_RAW_SHA256:
                raise EvidenceValidationError(
                    "US500 historical bytes differ from the precommitted snapshot"
                )
            if canonical_bytes(measurement) != canonical_bytes(expected):
                raise EvidenceValidationError("historical audit was not derived from raw bytes")
            facts = dict(expected["facts"])
            required_fields = HISTORICAL_FACT_FIELDS
        else:
            if len(measurement_names) != 1 or not measurement_names[0].endswith(".json"):
                raise EvidenceValidationError("runtime source outputs are not exact")
            try:
                probe = parse_canonical(contents[measurement_names[0]])
            except ValueError as exc:
                raise EvidenceValidationError("runtime probe is not canonical") from exc
            probe = _mapping(probe, "runtime probe")
            if (
                probe.get("schema") != "us500_runtime_probe_measurement.v1"
                or probe.get("source_contract_id") != source_id
                or probe.get("observed_at_utc") != observed_at
            ):
                raise EvidenceValidationError("runtime probe provenance is invalid")
            facts = derive_runtime_facts(probe)
            if canonical_bytes(probe.get("facts")) != canonical_bytes(facts):
                raise EvidenceValidationError("runtime facts were not derived from probe")
            required_fields = RUNTIME_FACT_FIELDS
        if set(facts) != set(required_fields):
            raise EvidenceValidationError("source fact fields differ from plan")
        for name in required_fields:
            value = facts[name]
            if name == "latency_ms":
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise EvidenceValidationError("runtime latency is invalid")
            elif value is not True:
                raise EvidenceValidationError(f"source eligibility fact failed: {name}")
        if canonical_bytes(result.get("facts")) != canonical_bytes(facts):
            raise EvidenceValidationError("result facts differ from derived facts")
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=measurement_hashes,
            facts={**facts, "observed_at_utc": observed_at},
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = ["SOURCE_ELIGIBILITY_VALIDATOR_ID", "SourceEligibilityValidator"]


