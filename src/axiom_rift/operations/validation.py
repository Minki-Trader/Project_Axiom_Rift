"""Late-bound evidence validators at scientific and engine trust boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


class EvidenceValidationError(RuntimeError):
    """Evidence could not be derived by a registered validator."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EvidenceValidationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise EvidenceValidationError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def validator_implementation_sha256(
    *,
    implementation_path: str | Path,
    dependency_paths: tuple[str | Path, ...] = (),
) -> str:
    """Bind one implementation and its ordered, declared dependency bytes."""

    if type(dependency_paths) is not tuple:
        raise EvidenceValidationError(
            "validator dependency paths must be a declared tuple"
        )

    def regular_file(value: str | Path, *, label: str) -> Path:
        try:
            raw = Path(value)
            if raw.is_symlink():
                raise EvidenceValidationError(f"{label} must not be a symlink")
            path = raw.resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise EvidenceValidationError(f"{label} is invalid or absent") from exc
        if not path.is_file():
            raise EvidenceValidationError(f"{label} must be a regular file")
        return path

    implementation = regular_file(
        implementation_path,
        label="validator implementation",
    )
    dependencies = tuple(
        regular_file(item, label="validator dependency")
        for item in dependency_paths
    )
    if (
        len(set(dependencies)) != len(dependencies)
        or implementation in dependencies
    ):
        raise EvidenceValidationError(
            "validator dependency paths must be unique"
        )

    def content_digest(path: Path, *, dependency: bool) -> str:
        try:
            content = path.read_bytes()
        except OSError as exc:
            label = "dependency" if dependency else "implementation"
            raise EvidenceValidationError(
                f"validator {label} file is absent"
            ) from exc
        return sha256(content).hexdigest()

    implementation_digest = content_digest(implementation, dependency=False)
    if not dependencies:
        return implementation_digest
    dependency_digests = [
        content_digest(path, dependency=True) for path in dependencies
    ]
    return canonical_digest(
        domain="evidence-validator-implementation-bundle",
        payload={
            "dependency_sha256s": dependency_digests,
            "implementation_sha256": implementation_digest,
            "schema": "evidence_validator_implementation_bundle.v1",
        },
    )


def validator_identity(
    *,
    protocol: str,
    domains: frozenset[str],
    implementation_sha256: str,
) -> str:
    _ascii("validator protocol", protocol)
    _digest("validator implementation", implementation_sha256)
    return "validator:" + canonical_digest(
        domain="evidence-validator",
        payload={
            "domains": sorted(domains),
            "implementation_sha256": implementation_sha256,
            "protocol": protocol,
        },
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationArtifact:
    output_name: str
    sha256: str
    _source: Path = field(repr=False)
    _content: bytes = field(init=False, repr=False)
    _read_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        _ascii("output_name", self.output_name)
        _digest("artifact sha256", self.sha256)
        try:
            content = self._source.read_bytes()
        except OSError as exc:
            raise EvidenceValidationError("validation artifact is absent") from exc
        if sha256(content).hexdigest() != self.sha256:
            raise EvidenceValidationError(
                "validation artifact changed before dispatch"
            )
        object.__setattr__(self, "_content", content)

    def read_bytes(self) -> bytes:
        object.__setattr__(self, "_read_count", self._read_count + 1)
        return self._content

    def require_source_unchanged(self) -> None:
        try:
            content = self._source.read_bytes()
        except OSError as exc:
            raise EvidenceValidationError(
                "validation artifact disappeared during validation"
            ) from exc
        if sha256(content).hexdigest() != self.sha256:
            raise EvidenceValidationError(
                "validation artifact changed during validation"
            )

    @property
    def was_read(self) -> bool:
        return self._read_count > 0


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceValidationRequest:
    domain: str
    validator_id: str
    validation_plan_hash: str
    job_id: str
    job_hash: str
    mission_id: str
    evidence_subject: Mapping[str, str]
    binding: Mapping[str, Any]
    result_manifest: Mapping[str, Any]
    artifacts: tuple[ValidationArtifact, ...]
    engineering_fixture: bool = False

    def __post_init__(self) -> None:
        if self.domain not in {"scientific", "source", "runtime", "external"}:
            raise EvidenceValidationError("validation domain is not typed")
        validator_digest = _ascii(
            "validator_id",
            self.validator_id,
        ).removeprefix("validator:")
        _digest("validator identity", validator_digest)
        _digest("validation_plan_hash", self.validation_plan_hash)
        for name in ("job_id", "job_hash", "mission_id"):
            _ascii(name, getattr(self, name))
        if not self.artifacts:
            raise EvidenceValidationError(
                "validator requires declared durable artifacts"
            )
        object.__setattr__(
            self,
            "evidence_subject",
            _freeze_canonical(self.evidence_subject),
        )
        object.__setattr__(self, "binding", _freeze_canonical(self.binding))
        object.__setattr__(
            self,
            "result_manifest",
            _freeze_canonical(self.result_manifest),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EngineeringEvidenceValidationRequest:
    """An exact failed-Job retry validation at the engineering boundary."""

    validator_id: str
    validation_plan_hash: str
    mission_id: str
    retry_family_fingerprint: str
    prior_completion_record_id: str
    prior_job_id: str
    prior_job_hash: str
    prior_work_fingerprint: str
    new_work_fingerprint: str
    changed_dimension: str
    new_basis_hash: str
    evidence_subject: Mapping[str, str]
    binding: Mapping[str, Any]
    result_manifest: Mapping[str, Any]
    artifacts: tuple[ValidationArtifact, ...]
    engineering_fixture: bool = False
    domain: str = field(default="engineering", init=False)

    def __post_init__(self) -> None:
        validator_digest = _ascii(
            "validator_id",
            self.validator_id,
        ).removeprefix("validator:")
        _digest("validator identity", validator_digest)
        for name, value in (
            ("validation_plan_hash", self.validation_plan_hash),
            ("retry family fingerprint", self.retry_family_fingerprint),
            ("prior completion record", self.prior_completion_record_id),
            ("prior Job hash", self.prior_job_hash),
            ("prior work fingerprint", self.prior_work_fingerprint),
            ("new work fingerprint", self.new_work_fingerprint),
            ("new retry basis", self.new_basis_hash),
        ):
            _digest(name, value)
        prior_job = _ascii("prior Job", self.prior_job_id)
        if not prior_job.startswith("job:"):
            raise EvidenceValidationError("prior Job identity prefix is invalid")
        _digest("prior Job identity", prior_job.removeprefix("job:"))
        _ascii("mission_id", self.mission_id)
        if self.changed_dimension not in {
            "cause",
            "compute_budget",
            "implementation",
            "information",
        }:
            raise EvidenceValidationError(
                "engineering validation changed dimension is invalid"
            )
        if not self.artifacts:
            raise EvidenceValidationError(
                "engineering validator requires durable artifacts"
            )
        if (
            not isinstance(self.evidence_subject, Mapping)
            or set(self.evidence_subject) != {"id", "kind"}
        ):
            raise EvidenceValidationError(
                "engineering validation evidence subject is invalid"
            )
        _ascii("evidence subject kind", self.evidence_subject.get("kind"))
        _ascii("evidence subject id", self.evidence_subject.get("id"))
        object.__setattr__(
            self,
            "evidence_subject",
            _freeze_canonical(self.evidence_subject),
        )
        object.__setattr__(self, "binding", _freeze_canonical(self.binding))
        object.__setattr__(
            self,
            "result_manifest",
            _freeze_canonical(self.result_manifest),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalChangeValidationRequest:
    """A non-Job validator request at an exact blocked-Mission boundary."""

    validator_id: str
    validation_plan_hash: str
    boundary_id: str
    condition_id: str
    mission_id: str
    evidence_subject: Mapping[str, str]
    binding: Mapping[str, Any]
    result_manifest: Mapping[str, Any]
    artifacts: tuple[ValidationArtifact, ...]
    engineering_fixture: bool = False
    domain: str = field(default="external", init=False)

    def __post_init__(self) -> None:
        validator_digest = _ascii(
            "validator_id",
            self.validator_id,
        ).removeprefix("validator:")
        _digest("validator identity", validator_digest)
        _digest("validation_plan_hash", self.validation_plan_hash)
        _digest("blocked Mission boundary", self.boundary_id)
        condition_identity = _ascii(
            "external resume condition",
            self.condition_id,
        )
        if not condition_identity.startswith("external-resume-condition:"):
            raise EvidenceValidationError(
                "external resume condition identity prefix is invalid"
            )
        condition_digest = condition_identity.removeprefix(
            "external-resume-condition:"
        )
        _digest("external resume condition identity", condition_digest)
        _ascii("mission_id", self.mission_id)
        if not self.artifacts:
            raise EvidenceValidationError(
                "external change validator requires durable artifacts"
            )
        object.__setattr__(
            self,
            "evidence_subject",
            _freeze_canonical(self.evidence_subject),
        )
        object.__setattr__(self, "binding", _freeze_canonical(self.binding))
        object.__setattr__(
            self,
            "result_manifest",
            _freeze_canonical(self.result_manifest),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedEvidence:
    verdict: str
    claims: tuple[str, ...] = ()
    measurement_artifact_hashes: tuple[str, ...] = ()
    artifact_roles: tuple[tuple[str, str], ...] = ()
    facts: Mapping[str, Any] = field(default_factory=dict)
    scientific_eligible: bool = False
    candidate_eligible: bool = False
    release_eligible: bool = False

    def __post_init__(self) -> None:
        if self.verdict not in {"passed", "failed", "not_evaluable"}:
            raise EvidenceValidationError("validator verdict is not typed")
        claims = tuple(sorted(_ascii("claim", item) for item in self.claims))
        if len(set(claims)) != len(claims):
            raise EvidenceValidationError("validator claims must be unique")
        hashes = tuple(
            sorted(
                _digest("measurement artifact", item)
                for item in self.measurement_artifact_hashes
            )
        )
        if len(set(hashes)) != len(hashes):
            raise EvidenceValidationError(
                "measurement artifacts must be unique"
            )
        roles = tuple(sorted(self.artifact_roles))
        role_names: set[str] = set()
        role_hashes: set[str] = set()
        for role, artifact_hash in roles:
            _ascii("artifact role", role)
            _digest("role artifact", artifact_hash)
            if role in role_names or artifact_hash in role_hashes:
                raise EvidenceValidationError(
                    "artifact roles require unique names and distinct artifacts"
                )
            role_names.add(role)
            role_hashes.add(artifact_hash)
        if not isinstance(self.facts, Mapping):
            raise EvidenceValidationError("validator facts must be a mapping")
        canonical_bytes(dict(self.facts))
        if self.candidate_eligible and not self.scientific_eligible:
            raise EvidenceValidationError(
                "candidate eligibility requires scientific eligibility"
            )
        if self.release_eligible and not self.scientific_eligible:
            raise EvidenceValidationError(
                "Release eligibility requires scientific eligibility"
            )
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "measurement_artifact_hashes", hashes)
        object.__setattr__(self, "artifact_roles", roles)
        object.__setattr__(
            self,
            "facts",
            MappingProxyType(dict(self.facts)),
        )


class EvidenceValidator(Protocol):
    validator_id: str
    domains: frozenset[str]
    implementation_path: Path
    protocol: str

    def validate(
        self,
        request: (
            EngineeringEvidenceValidationRequest
            | EvidenceValidationRequest
            | ExternalChangeValidationRequest
        ),
    ) -> ValidatedEvidence: ...


@dataclass(frozen=True, slots=True)
class ValidationTrace:
    validator_id: str
    declared_artifact_count: int
    opened_artifact_count: int


def _build_validator_registration(validator: object) -> Any:
    from axiom_rift.operations.validation_integrity import (
        _build_validator_registration as build,
    )

    return build(validator)


def _require_validator_registration_unchanged(registration: object) -> None:
    from axiom_rift.operations.validation_integrity import (
        _require_validator_registration_unchanged as require_unchanged,
    )

    require_unchanged(registration)


class EvidenceValidatorRegistry:
    """Small trusted adapter registry with an intentionally empty default."""

    def __init__(self, validators: tuple[EvidenceValidator, ...] = ()) -> None:
        registrations: dict[str, Any] = {}
        for validator in validators:
            registration = _build_validator_registration(validator)
            validator_id = registration.integrity.validator_id
            if validator_id in registrations:
                raise EvidenceValidationError(
                    "validator identity is duplicated"
                )
            registrations[validator_id] = registration
        self._registrations = MappingProxyType(registrations)

    def _require_unchanged(self, registration: object) -> None:
        _require_validator_registration_unchanged(registration)

    def _authorized_registration(
        self,
        *,
        validator_id: str,
        domain: str,
    ) -> Any:
        registration = self._registrations.get(validator_id)
        if (
            registration is None
            or domain not in registration.integrity.domains
        ):
            raise EvidenceValidationError(
                "no registered validator authorizes this evidence domain"
            )
        self._require_unchanged(registration)
        return registration

    def validate(
        self,
        request: (
            EngineeringEvidenceValidationRequest
            | EvidenceValidationRequest
            | ExternalChangeValidationRequest
        ),
    ) -> tuple[ValidatedEvidence, ValidationTrace]:
        registration = self._authorized_registration(
            validator_id=request.validator_id,
            domain=request.domain,
        )
        try:
            result = registration.validate(request)
            if not isinstance(result, ValidatedEvidence):
                raise EvidenceValidationError(
                    "validator returned an untyped result"
                )
            opened = sum(artifact.was_read for artifact in request.artifacts)
            if opened != len(request.artifacts):
                raise EvidenceValidationError(
                    "validator did not inspect every declared artifact"
                )
            for artifact in request.artifacts:
                artifact.require_source_unchanged()
            trace = ValidationTrace(
                validator_id=request.validator_id,
                declared_artifact_count=len(request.artifacts),
                opened_artifact_count=opened,
            )
        finally:
            # One post boundary covers dispatch, result typing, declared-artifact
            # inspection, and durable-source stability.  Together with the
            # authorization boundary this is the exact pre/post pair.
            self._require_unchanged(registration)
        return result, trace

    def require_registered(self, *, validator_id: str, domain: str) -> None:
        self._authorized_registration(
            validator_id=validator_id,
            domain=domain,
        )

    def require_registered_protocol(
        self,
        *,
        validator_id: str,
        domain: str,
        protocol: str,
    ) -> None:
        """Require one immutable validator registration with exact protocol."""

        if type(protocol) is not str or not protocol or not protocol.isascii():
            raise EvidenceValidationError(
                "validator protocol requirement is invalid"
            )
        registration = self._authorized_registration(
            validator_id=validator_id,
            domain=domain,
        )
        if registration.integrity.protocol != protocol:
            raise EvidenceValidationError(
                "registered validator protocol differs from the required capability"
            )

    def preflight_binding(
        self,
        *,
        validator_id: str,
        domain: str,
        binding: Mapping[str, Any],
    ) -> None:
        """Fail before engine work when a validator rejects its frozen binding."""

        registration = self._authorized_registration(
            validator_id=validator_id,
            domain=domain,
        )
        if registration.preflight is None:
            return
        try:
            registration.preflight(
                domain=domain,
                binding=_freeze_canonical(binding),
            )
        finally:
            self._require_unchanged(registration)


ENGINEERING_RUNTIME_PLAN = {
    "schema": "engineering_runtime_validation_plan.v1",
    "authority": "fixture_only",
}
ENGINEERING_RUNTIME_PLAN_HASH = canonical_digest(
    domain="validation-plan",
    payload=ENGINEERING_RUNTIME_PLAN,
)


def _thaw_canonical(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _thaw_canonical(child) for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_thaw_canonical(child) for child in value]
    return value


def _freeze_canonical(value: object) -> Any:
    """Canonical-copy caller state, then expose only immutable containers."""

    copied = parse_canonical(canonical_bytes(_thaw_canonical(value)))

    def freeze(item: Any) -> Any:
        if type(item) is dict:
            return MappingProxyType(
                {key: freeze(child) for key, child in item.items()}
            )
        if type(item) is list:
            return tuple(freeze(child) for child in item)
        return item

    return freeze(copied)


_THIS_IMPLEMENTATION = Path(__file__).resolve()
ENGINEERING_VALIDATOR_ID = validator_identity(
    protocol="engineering_fixture.v1",
    domains=frozenset({"runtime", "scientific"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION
    ),
)


class EngineeringFixtureValidator:
    """Deterministic boundary fixture; it cannot authorize science or Release."""

    validator_id = ENGINEERING_VALIDATOR_ID
    domains = frozenset({"runtime", "scientific"})
    implementation_path = _THIS_IMPLEMENTATION
    protocol = "engineering_fixture.v1"

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if (
            not request.engineering_fixture
            or request.domain != "runtime"
            or request.validation_plan_hash != ENGINEERING_RUNTIME_PLAN_HASH
        ):
            raise EvidenceValidationError(
                "engineering validator is fixture-only"
            )
        artifacts = {
            artifact.sha256: artifact for artifact in request.artifacts
        }
        observations = request.result_manifest.get("observations")
        if not isinstance(observations, tuple) or not observations:
            raise EvidenceValidationError("fixture result has no observations")
        measurement_hashes = {
            observation.get("measurement_artifact_hash")
            for observation in observations
            if isinstance(observation, Mapping)
        }
        if None in measurement_hashes or not measurement_hashes.issubset(
            artifacts
        ):
            raise EvidenceValidationError(
                "fixture observation is not artifact-bound"
            )
        coverage_ids: list[str] = []
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise EvidenceValidationError(
                    "fixture observation is not a mapping"
                )
            coverage_id = observation.get("source_lifecycle_coverage_id")
            if coverage_id is None:
                continue
            coverage_identity = _ascii(
                "source lifecycle coverage identity",
                coverage_id,
            )
            prefix = "source-lifecycle-coverage:"
            if not coverage_identity.startswith(prefix):
                raise EvidenceValidationError(
                    "source lifecycle coverage identity prefix is invalid"
                )
            _digest(
                "source lifecycle coverage identity",
                coverage_identity.removeprefix(prefix),
            )
            coverage_ids.append(coverage_identity)
        if len(set(coverage_ids)) != len(coverage_ids):
            raise EvidenceValidationError(
                "fixture source lifecycle coverage is duplicated"
            )
        derived_claims: set[str] = set()
        for artifact_hash in measurement_hashes:
            artifact = artifacts[artifact_hash]
            try:
                packet = parse_canonical(artifact.read_bytes())
            except ValueError as exc:
                raise EvidenceValidationError(
                    "fixture measurement is not canonical"
                ) from exc
            if (
                not isinstance(packet, dict)
                or set(packet) != {"claims", "schema"}
                or packet["schema"]
                != "engineering_runtime_measurement.v1"
                or not isinstance(packet["claims"], list)
            ):
                raise EvidenceValidationError(
                    "fixture measurement schema is invalid"
                )
            for claim in packet["claims"]:
                derived_claims.add(_ascii("fixture claim", claim))
        observed_claims = {
            observation.get("claim_id")
            for observation in observations
            if isinstance(observation, Mapping)
        }
        if derived_claims != observed_claims:
            raise EvidenceValidationError(
                "caller claims differ from fixture measurements"
            )
        role_bindings = request.binding.get("artifact_roles")
        if not isinstance(role_bindings, Mapping):
            raise EvidenceValidationError("fixture artifact roles are absent")
        by_output = {
            artifact.output_name: artifact.sha256
            for artifact in request.artifacts
        }
        roles = tuple(
            (role, by_output[output])
            for role, output in role_bindings.items()
        )
        for artifact in request.artifacts:
            if not artifact.was_read:
                artifact.read_bytes()
        return ValidatedEvidence(
            verdict="passed",
            claims=tuple(derived_claims),
            measurement_artifact_hashes=tuple(measurement_hashes),
            artifact_roles=roles,
            facts={
                "source_lifecycle_coverage_ids": sorted(coverage_ids),
            },
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


ENGINEERING_RETRY_FIXTURE_PROTOCOL = "engineering_retry_fixture.v1"
ENGINEERING_RETRY_VALIDATOR_ID = validator_identity(
    protocol=ENGINEERING_RETRY_FIXTURE_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION
    ),
)


class EngineeringRetryFixtureValidator:
    """Fixture-only retry validator that recomputes a canonical transition."""

    validator_id = ENGINEERING_RETRY_VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_IMPLEMENTATION
    protocol = ENGINEERING_RETRY_FIXTURE_PROTOCOL

    def validate(
        self,
        request: EngineeringEvidenceValidationRequest,
    ) -> ValidatedEvidence:
        if (
            not isinstance(request, EngineeringEvidenceValidationRequest)
            or not request.engineering_fixture
            or request.domain != "engineering"
        ):
            raise EvidenceValidationError(
                "engineering retry validator is fixture-only"
            )
        plans = tuple(
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
            len(plans) != 1
            or not measurements
            or len(plans) + len(measurements) != len(request.artifacts)
        ):
            raise EvidenceValidationError(
                "engineering retry fixture artifact roles are invalid"
            )
        try:
            plan = parse_canonical(plans[0].read_bytes())
        except (TypeError, ValueError) as exc:
            raise EvidenceValidationError(
                "engineering retry fixture plan is not canonical"
            ) from exc
        if plan != {
            "operation": "canonical_required_transition",
            "schema": "engineering_retry_fixture_plan.v1",
        }:
            raise EvidenceValidationError(
                "engineering retry fixture plan is invalid"
            )
        binding = _thaw_canonical(request.binding)
        binding_sha256 = sha256(canonical_bytes(binding)).hexdigest()
        transition_hashes: list[str] = []
        for artifact in measurements:
            try:
                packet = parse_canonical(artifact.read_bytes())
            except (TypeError, ValueError) as exc:
                raise EvidenceValidationError(
                    "engineering retry fixture measurement is not canonical"
                ) from exc
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
                or packet.get("schema")
                != "engineering_retry_fixture_measurement.v1"
                or packet.get("binding_sha256") != binding_sha256
                or canonical_bytes(packet.get("prior_measurement"))
                == canonical_bytes(packet.get("required_measurement"))
                or canonical_bytes(packet.get("current_measurement"))
                != canonical_bytes(packet.get("required_measurement"))
            ):
                raise EvidenceValidationError(
                    "engineering retry fixture did not measure a resolved transition"
                )
            transition_hashes.append(
                canonical_digest(
                    domain="engineering-retry-fixture-transition",
                    payload=packet,
                )
            )
        artifact_roles = [
            ("validation_plan", plans[0].sha256),
            *(
                (f"cause_resolution_measurement_{index:04d}", artifact.sha256)
                for index, artifact in enumerate(measurements)
            ),
        ]
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=tuple(
                artifact.sha256 for artifact in measurements
            ),
            artifact_roles=tuple(artifact_roles),
            facts={
                "binding": binding,
                "cause_resolved": True,
                "material_change": True,
                "measurement_transition_hashes": sorted(transition_hashes),
            },
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


def __getattr__(name: str) -> Any:
    if name in {
        "validator_execution_dependency_paths",
        "validator_project_dependency_paths",
    }:
        from axiom_rift.operations import validation_integrity

        dependency_paths = getattr(validation_integrity, name)
        globals()[name] = dependency_paths
        return dependency_paths
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ENGINEERING_RETRY_FIXTURE_PROTOCOL",
    "ENGINEERING_RETRY_VALIDATOR_ID",
    "ENGINEERING_RUNTIME_PLAN_HASH",
    "ENGINEERING_VALIDATOR_ID",
    "EngineeringFixtureValidator",
    "EngineeringRetryFixtureValidator",
    "EngineeringEvidenceValidationRequest",
    "ExternalChangeValidationRequest",
    "EvidenceValidationError",
    "EvidenceValidationRequest",
    "EvidenceValidator",
    "EvidenceValidatorRegistry",
    "ValidatedEvidence",
    "ValidationArtifact",
    "ValidationTrace",
    "validator_implementation_sha256",
    "validator_identity",
    "validator_execution_dependency_paths",
    "validator_project_dependency_paths",
]
