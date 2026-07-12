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
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise EvidenceValidationError(f"{name} must be a lowercase SHA-256 digest")
    return text


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
            raise EvidenceValidationError("validation artifact changed before dispatch")
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
        validator_digest = _ascii("validator_id", self.validator_id).removeprefix(
            "validator:"
        )
        _digest("validator identity", validator_digest)
        _digest("validation_plan_hash", self.validation_plan_hash)
        for name in ("job_id", "job_hash", "mission_id"):
            _ascii(name, getattr(self, name))
        if not self.artifacts:
            raise EvidenceValidationError("validator requires declared durable artifacts")
        object.__setattr__(
            self, "evidence_subject", _freeze_canonical(self.evidence_subject)
        )
        object.__setattr__(self, "binding", _freeze_canonical(self.binding))
        object.__setattr__(
            self, "result_manifest", _freeze_canonical(self.result_manifest)
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
            sorted(_digest("measurement artifact", item) for item in self.measurement_artifact_hashes)
        )
        if len(set(hashes)) != len(hashes):
            raise EvidenceValidationError("measurement artifacts must be unique")
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
            raise EvidenceValidationError("candidate eligibility requires scientific eligibility")
        if self.release_eligible and not self.scientific_eligible:
            raise EvidenceValidationError("Release eligibility requires scientific eligibility")
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "measurement_artifact_hashes", hashes)
        object.__setattr__(self, "artifact_roles", roles)
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))


class EvidenceValidator(Protocol):
    validator_id: str
    domains: frozenset[str]
    implementation_path: Path
    protocol: str

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence: ...


@dataclass(frozen=True, slots=True)
class ValidationTrace:
    validator_id: str
    declared_artifact_count: int
    opened_artifact_count: int


class EvidenceValidatorRegistry:
    """Small trusted adapter registry. The production default is intentionally empty."""

    def __init__(self, validators: tuple[EvidenceValidator, ...] = ()) -> None:
        self._validators: dict[str, EvidenceValidator] = {}
        for validator in validators:
            validator_id = _ascii("validator_id", validator.validator_id)
            if validator_id in self._validators:
                raise EvidenceValidationError("validator identity is duplicated")
            if not validator.domains or not validator.domains.issubset(
                {"scientific", "source", "runtime", "external"}
            ):
                raise EvidenceValidationError("validator domains are invalid")
            implementation_path = Path(validator.implementation_path).resolve()
            if not implementation_path.is_file():
                raise EvidenceValidationError("validator implementation file is absent")
            implementation_hash = sha256(implementation_path.read_bytes()).hexdigest()
            expected_id = validator_identity(
                protocol=validator.protocol,
                domains=validator.domains,
                implementation_sha256=implementation_hash,
            )
            if validator_id != expected_id:
                raise EvidenceValidationError(
                    "validator identity does not bind its implementation file"
                )
            self._validators[validator_id] = validator

    def validate(
        self, request: EvidenceValidationRequest
    ) -> tuple[ValidatedEvidence, ValidationTrace]:
        validator = self._validators.get(request.validator_id)
        if validator is None or request.domain not in validator.domains:
            raise EvidenceValidationError(
                "no registered validator authorizes this evidence domain"
            )
        result = validator.validate(request)
        if not isinstance(result, ValidatedEvidence):
            raise EvidenceValidationError("validator returned an untyped result")
        opened = sum(artifact.was_read for artifact in request.artifacts)
        if opened != len(request.artifacts):
            raise EvidenceValidationError(
                "validator did not inspect every declared artifact"
            )
        for artifact in request.artifacts:
            artifact.require_source_unchanged()
        return result, ValidationTrace(
            validator_id=request.validator_id,
            declared_artifact_count=len(request.artifacts),
            opened_artifact_count=opened,
        )

    def require_registered(self, *, validator_id: str, domain: str) -> None:
        validator = self._validators.get(validator_id)
        if validator is None or domain not in validator.domains:
            raise EvidenceValidationError(
                "no registered validator authorizes this evidence domain"
            )

    def preflight_binding(
        self,
        *,
        validator_id: str,
        domain: str,
        binding: Mapping[str, Any],
    ) -> None:
        """Fail before engine work when a validator rejects its frozen binding."""

        self.require_registered(validator_id=validator_id, domain=domain)
        validator = self._validators[validator_id]
        preflight = getattr(validator, "preflight_binding", None)
        if preflight is None:
            return
        if not callable(preflight):
            raise EvidenceValidationError("validator binding preflight is invalid")
        preflight(domain=domain, binding=_freeze_canonical(binding))


ENGINEERING_RUNTIME_PLAN = {
    "schema": "engineering_runtime_validation_plan.v1",
    "authority": "fixture_only",
}
ENGINEERING_RUNTIME_PLAN_HASH = canonical_digest(
    domain="validation-plan", payload=ENGINEERING_RUNTIME_PLAN
)


def _freeze_canonical(value: object) -> Any:
    """Canonical-copy caller state, then expose only immutable containers."""

    def thaw(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: thaw(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [thaw(child) for child in item]
        return item

    copied = parse_canonical(canonical_bytes(thaw(value)))

    def freeze(item: Any) -> Any:
        if type(item) is dict:
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if type(item) is list:
            return tuple(freeze(child) for child in item)
        return item

    return freeze(copied)


def validator_identity(
    *, protocol: str, domains: frozenset[str], implementation_sha256: str
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


_THIS_IMPLEMENTATION = Path(__file__).resolve()
ENGINEERING_VALIDATOR_ID = validator_identity(
    protocol="engineering_fixture.v1",
    domains=frozenset({"runtime", "scientific"}),
    implementation_sha256=sha256(_THIS_IMPLEMENTATION.read_bytes()).hexdigest(),
)


class EngineeringFixtureValidator:
    """Deterministic boundary fixture; it can never authorize science or Release."""

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
            raise EvidenceValidationError("engineering validator is fixture-only")
        artifacts = {artifact.sha256: artifact for artifact in request.artifacts}
        observations = request.result_manifest.get("observations")
        if not isinstance(observations, tuple) or not observations:
            raise EvidenceValidationError("fixture result has no observations")
        measurement_hashes = {
            observation.get("measurement_artifact_hash")
            for observation in observations
            if isinstance(observation, Mapping)
        }
        if None in measurement_hashes or not measurement_hashes.issubset(artifacts):
            raise EvidenceValidationError("fixture observation is not artifact-bound")
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
                or packet["schema"] != "engineering_runtime_measurement.v1"
                or not isinstance(packet["claims"], list)
            ):
                raise EvidenceValidationError("fixture measurement schema is invalid")
            for claim in packet["claims"]:
                derived_claims.add(_ascii("fixture claim", claim))
        observed_claims = {
            observation.get("claim_id")
            for observation in observations
            if isinstance(observation, Mapping)
        }
        if derived_claims != observed_claims:
            raise EvidenceValidationError("caller claims differ from fixture measurements")
        role_bindings = request.binding.get("artifact_roles")
        if not isinstance(role_bindings, Mapping):
            raise EvidenceValidationError("fixture artifact roles are absent")
        by_output = {artifact.output_name: artifact.sha256 for artifact in request.artifacts}
        roles = tuple((role, by_output[output]) for role, output in role_bindings.items())
        for artifact in request.artifacts:
            if not artifact.was_read:
                artifact.read_bytes()
        return ValidatedEvidence(
            verdict="passed",
            claims=tuple(derived_claims),
            measurement_artifact_hashes=tuple(measurement_hashes),
            artifact_roles=roles,
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "ENGINEERING_RUNTIME_PLAN_HASH",
    "ENGINEERING_VALIDATOR_ID",
    "EngineeringFixtureValidator",
    "EvidenceValidationError",
    "EvidenceValidationRequest",
    "EvidenceValidator",
    "EvidenceValidatorRegistry",
    "ValidatedEvidence",
    "ValidationArtifact",
    "ValidationTrace",
    "validator_identity",
]
