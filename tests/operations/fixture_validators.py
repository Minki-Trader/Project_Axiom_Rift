from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
)


IMPLEMENTATION_PATH = Path(__file__).resolve()
IMPLEMENTATION_HASH = sha256(IMPLEMENTATION_PATH.read_bytes()).hexdigest()


class ScientificFixtureValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "scientific_boundary_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        claims: set[str] = set()
        verdicts: set[str] = set()
        candidate_flags: set[bool] = set()
        executed_mode_sets: set[tuple[str, ...]] = set()
        hashes: list[str] = []
        for artifact in request.artifacts:
            artifact_bytes = artifact.read_bytes()
            if artifact.output_name == request.binding.get("result_manifest_output"):
                continue
            value = parse_canonical(artifact_bytes)
            if (
                not isinstance(value, dict)
                or set(value)
                != {
                    "candidate_eligible",
                    "claim_id",
                    "executed_evidence_modes",
                    "schema",
                    "verdict",
                }
                or value["schema"] != "scientific_boundary_measurement.v1"
                or value["verdict"] not in {"passed", "failed", "not_evaluable"}
                or type(value["candidate_eligible"]) is not bool
                or type(value["claim_id"]) is not str
                or not isinstance(value["executed_evidence_modes"], list)
                or not value["executed_evidence_modes"]
                or any(
                    type(mode) is not str
                    for mode in value["executed_evidence_modes"]
                )
                or value["executed_evidence_modes"]
                != sorted(set(value["executed_evidence_modes"]))
            ):
                raise EvidenceValidationError("scientific fixture measurement is invalid")
            claims.add(value["claim_id"])
            verdicts.add(value["verdict"])
            candidate_flags.add(value["candidate_eligible"])
            executed_mode_sets.add(tuple(value["executed_evidence_modes"]))
            hashes.append(artifact.sha256)
        planned = set(request.binding.get("planned_claims", ()))
        if (
            claims != planned
            or len(verdicts) != 1
            or len(candidate_flags) != 1
            or executed_mode_sets
            != {tuple(request.binding.get("evidence_modes", ()))}
        ):
            raise EvidenceValidationError("scientific fixture claims are inconsistent")
        verdict = next(iter(verdicts))
        candidate_eligible = next(iter(candidate_flags))
        if candidate_eligible != (
            verdict == "passed"
            and request.binding.get("evidence_depth") == "confirmation"
        ):
            raise EvidenceValidationError("scientific fixture eligibility is invalid")
        return ValidatedEvidence(
            verdict=verdict,
            claims=tuple(claims),
            measurement_artifact_hashes=tuple(hashes),
            facts={"executed_evidence_modes": list(next(iter(executed_mode_sets)))},
            scientific_eligible=True,
            candidate_eligible=candidate_eligible,
        )


class ExternalFixtureValidator:
    domains = frozenset({"external"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "external_boundary_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        measurements = []
        for artifact in request.artifacts:
            artifact_bytes = artifact.read_bytes()
            if artifact.output_name == request.binding.get("result_manifest_output"):
                continue
            measurements.append((artifact, artifact_bytes))
        if len(measurements) != 1:
            raise EvidenceValidationError("external fixture requires one measurement")
        artifact, artifact_bytes = measurements[0]
        value = parse_canonical(artifact_bytes)
        if (
            not isinstance(value, dict)
            or set(value) != {"facts", "schema", "verdict"}
            or value["schema"] != "external_boundary_measurement.v1"
            or value["verdict"] not in {"passed", "failed", "not_evaluable"}
            or not isinstance(value["facts"], Mapping)
        ):
            raise EvidenceValidationError("external fixture measurement is invalid")
        return ValidatedEvidence(
            verdict=value["verdict"],
            measurement_artifact_hashes=(artifact.sha256,),
            facts=dict(value["facts"]),
        )


class ComponentParityFixtureValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "component_parity_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        measurements: list[tuple[object, object]] = []
        for artifact in request.artifacts:
            content = artifact.read_bytes()
            if artifact.output_name == request.binding.get("result_manifest_output"):
                continue
            measurements.append((artifact, parse_canonical(content)))
        if len(measurements) != 1:
            raise EvidenceValidationError(
                "component parity fixture requires one measurement"
            )
        artifact, value = measurements[0]
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "canonical_component_id",
                "dimensions",
                "equivalent",
                "equivalent_component_id",
                "schema",
            }
            or value["schema"] != "component_parity_measurement.v1"
            or type(value["equivalent"]) is not bool
            or value["canonical_component_id"]
            != request.binding.get("canonical_component_id")
            or value["equivalent_component_id"]
            != request.binding.get("equivalent_component_id")
            or list(value["dimensions"])
            != list(request.binding.get("dimensions", ()))
        ):
            raise EvidenceValidationError(
                "component parity fixture measurement is invalid"
            )
        return ValidatedEvidence(
            verdict="passed" if value["equivalent"] else "failed",
            measurement_artifact_hashes=(artifact.sha256,),
            facts={
                "canonical_component_id": value["canonical_component_id"],
                "dimensions": list(value["dimensions"]),
                "equivalent": value["equivalent"],
                "equivalent_component_id": value["equivalent_component_id"],
            },
        )


__all__ = [
    "ComponentParityFixtureValidator",
    "ExternalFixtureValidator",
    "ScientificFixtureValidator",
]
