from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EngineeringEvidenceValidationRequest,
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
)


IMPLEMENTATION_PATH = Path(__file__).resolve()
IMPLEMENTATION_HASH = sha256(IMPLEMENTATION_PATH.read_bytes()).hexdigest()
RUNTIME_BOUNDARY_PLAN_HASH = canonical_digest(
    domain="validation-plan",
    payload={"schema": "runtime_boundary_fixture.v1"},
)
SOURCE_BOUNDARY_PLAN_HASH = canonical_digest(
    domain="validation-plan",
    payload={"schema": "source_boundary_fixture.v1"},
)


def _plain_canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _plain_canonical(child) for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_canonical(child) for child in value]
    return value


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


class RuntimeBoundaryFixtureValidator:
    """Test adapter for exercising production-mode runtime state routing."""

    domains = frozenset({"runtime"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "runtime_boundary_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if request.validation_plan_hash != RUNTIME_BOUNDARY_PLAN_HASH:
            raise EvidenceValidationError("runtime fixture plan is not bound")
        by_output = {}
        for artifact in request.artifacts:
            artifact.read_bytes()
            by_output[artifact.output_name] = artifact.sha256
        observations = request.result_manifest.get("observations")
        if not isinstance(observations, tuple) or not observations:
            raise EvidenceValidationError("runtime fixture observations are absent")
        claims: set[str] = set()
        measurements: set[str] = set()
        source_lifecycle_coverage_ids: set[str] = set()
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise EvidenceValidationError("runtime fixture observation is invalid")
            claim = observation.get("claim_id")
            measurement = observation.get("measurement_artifact_hash")
            if type(claim) is not str or type(measurement) is not str:
                raise EvidenceValidationError("runtime fixture observation is untyped")
            claims.add(claim)
            measurements.add(measurement)
            coverage_id = observation.get("source_lifecycle_coverage_id")
            if coverage_id is not None:
                if type(coverage_id) is not str:
                    raise EvidenceValidationError(
                        "runtime fixture lifecycle coverage is untyped"
                    )
                source_lifecycle_coverage_ids.add(coverage_id)
        if not measurements.issubset(set(by_output.values())):
            raise EvidenceValidationError("runtime fixture measurement is undeclared")
        role_bindings = request.binding.get("artifact_roles")
        if not isinstance(role_bindings, Mapping):
            raise EvidenceValidationError("runtime fixture roles are absent")
        try:
            roles = tuple(
                (role, by_output[output_name])
                for role, output_name in role_bindings.items()
            )
        except KeyError as exc:
            raise EvidenceValidationError(
                "runtime fixture role output is undeclared"
            ) from exc
        return ValidatedEvidence(
            verdict="passed",
            claims=tuple(claims),
            measurement_artifact_hashes=tuple(measurements),
            artifact_roles=roles,
            facts={
                "source_lifecycle_coverage_ids": sorted(
                    source_lifecycle_coverage_ids
                )
            },
            scientific_eligible=True,
            release_eligible=True,
        )


class EngineeringRetryBoundaryFixtureValidator:
    """Test adapter for production-mode engineering retry validation."""

    domains = frozenset({"engineering"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "engineering_retry_boundary_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(
        self,
        request: EngineeringEvidenceValidationRequest,
    ) -> ValidatedEvidence:
        if not isinstance(request, EngineeringEvidenceValidationRequest):
            raise EvidenceValidationError(
                "engineering retry fixture request is untyped"
            )
        plan = tuple(
            artifact
            for artifact in request.artifacts
            if artifact.output_name == "validation_plan"
        )
        measurements = tuple(
            artifact
            for artifact in request.artifacts
            if artifact.output_name.startswith("validation_result:")
        )
        if (
            len(plan) != 1
            or not measurements
            or len(plan) + len(measurements) != len(request.artifacts)
        ):
            raise EvidenceValidationError(
                "engineering retry fixture artifacts are invalid"
            )
        if parse_canonical(plan[0].read_bytes()) != {
            "operation": "canonical_required_transition",
            "schema": "engineering_retry_fixture_plan.v1",
        }:
            raise EvidenceValidationError(
                "engineering retry fixture plan is invalid"
            )
        binding = _plain_canonical(request.binding)
        binding_sha256 = sha256(canonical_bytes(binding)).hexdigest()
        transition_hashes: list[str] = []
        for artifact in measurements:
            packet = parse_canonical(artifact.read_bytes())
            if (
                not isinstance(packet, dict)
                or set(packet)
                != {
                    "binding_sha256",
                    "current_measurement",
                    "prior_measurement",
                    "required_measurement",
                    "schema",
                }
                or packet["schema"]
                != "engineering_retry_fixture_measurement.v1"
                or packet["binding_sha256"] != binding_sha256
                or canonical_bytes(packet["prior_measurement"])
                == canonical_bytes(packet["required_measurement"])
                or canonical_bytes(packet["current_measurement"])
                != canonical_bytes(packet["required_measurement"])
            ):
                raise EvidenceValidationError(
                    "engineering retry fixture cause remains unresolved"
                )
            transition_hashes.append(
                canonical_digest(
                    domain="engineering-retry-boundary-fixture-transition",
                    payload=packet,
                )
            )
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=tuple(
                artifact.sha256 for artifact in measurements
            ),
            artifact_roles=(
                ("validation_plan", plan[0].sha256),
                *(
                    (
                        f"cause_resolution_measurement_{index:04d}",
                        artifact.sha256,
                    )
                    for index, artifact in enumerate(measurements)
                ),
            ),
            facts={
                "binding": binding,
                "cause_resolved": True,
                "material_change": True,
                "measurement_transition_hashes": sorted(transition_hashes),
            },
        )


class SourceBoundaryFixtureValidator:
    """Test adapter for production-mode source-transition routing."""

    domains = frozenset({"source"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "source_boundary_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if request.validation_plan_hash != SOURCE_BOUNDARY_PLAN_HASH:
            raise EvidenceValidationError("source fixture plan is not bound")
        result_output = request.binding.get("result_manifest_output")
        measurements = []
        for artifact in request.artifacts:
            artifact.read_bytes()
            if artifact.output_name != result_output:
                measurements.append(artifact.sha256)
        declared = request.result_manifest.get("measurement_artifact_hashes")
        facts = request.result_manifest.get("facts")
        observed_at = request.result_manifest.get("observed_at_utc")
        if (
            not isinstance(declared, tuple)
            or tuple(sorted(measurements)) != tuple(sorted(declared))
            or not isinstance(facts, Mapping)
            or type(observed_at) is not str
        ):
            raise EvidenceValidationError("source fixture result is inconsistent")
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=tuple(measurements),
            facts={**dict(facts), "observed_at_utc": observed_at},
        )


__all__ = [
    "ComponentParityFixtureValidator",
    "EngineeringRetryBoundaryFixtureValidator",
    "ExternalFixtureValidator",
    "RUNTIME_BOUNDARY_PLAN_HASH",
    "RuntimeBoundaryFixtureValidator",
    "ScientificFixtureValidator",
    "SOURCE_BOUNDARY_PLAN_HASH",
    "SourceBoundaryFixtureValidator",
]
