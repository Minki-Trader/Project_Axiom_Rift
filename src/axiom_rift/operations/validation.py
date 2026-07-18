"""Late-bound evidence validators at scientific and engine trust boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_disposition_case import (
    RepairDispositionCaseError,
    normalize_semantic_change_case,
    semantic_change_facts,
)
from axiom_rift.operations.repair_disposition_inventory import (
    RepairDispositionInventoryError,
    normalize_repair_inventory_facts,
)
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation_identity import (
    EvidenceValidationError,
    validator_identity,
    validator_implementation_sha256,
)


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
            raise EvidenceValidationError(
                "validation artifact is absent",
                reason_code="declared_artifact_absent_drifted_or_unopened",
            ) from exc
        if sha256(content).hexdigest() != self.sha256:
            raise EvidenceValidationError(
                "validation artifact changed before dispatch",
                reason_code="declared_artifact_absent_drifted_or_unopened",
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
                "validation artifact disappeared during validation",
                reason_code="declared_artifact_absent_drifted_or_unopened",
            ) from exc
        if sha256(content).hexdigest() != self.sha256:
            raise EvidenceValidationError(
                "validation artifact changed during validation",
                reason_code="declared_artifact_absent_drifted_or_unopened",
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
                "validator requires declared durable artifacts",
                reason_code="declared_artifact_absent_drifted_or_unopened",
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
class EngineeringRepairValidationRequest:
    """Independent validation of one Repair attempt or terminal disposition."""

    validator_id: str
    validation_plan_hash: str
    mission_id: str
    job_id: str
    job_hash: str
    repair_id: str | None
    verification_kind: str
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
        _digest("validation_plan_hash", self.validation_plan_hash)
        _ascii("mission_id", self.mission_id)
        job_id = _ascii("Repair validation Job", self.job_id)
        if not job_id.startswith("job:"):
            raise EvidenceValidationError(
                "Repair validation Job identity prefix is invalid"
            )
        _digest("Repair validation Job identity", job_id.removeprefix("job:"))
        _digest("Repair validation Job hash", self.job_hash)
        if self.repair_id is not None:
            repair_id = _ascii("Repair validation Repair", self.repair_id)
            if not repair_id.startswith("repair:"):
                raise EvidenceValidationError(
                    "Repair validation identity prefix is invalid"
                )
            _digest(
                "Repair validation identity",
                repair_id.removeprefix("repair:"),
            )
        if self.verification_kind not in {
            "attempt",
            "candidate",
            "disposition",
            "inventory",
            "semantic_change",
        }:
            raise EvidenceValidationError(
                "Repair validation kind is invalid"
            )
        if not self.artifacts:
            raise EvidenceValidationError(
                "Repair validator requires durable artifacts"
            )
        if (
            not isinstance(self.evidence_subject, Mapping)
            or set(self.evidence_subject) != {"id", "kind"}
        ):
            raise EvidenceValidationError(
                "Repair validation evidence subject is invalid"
            )
        _ascii("Repair evidence subject kind", self.evidence_subject.get("kind"))
        _ascii("Repair evidence subject id", self.evidence_subject.get("id"))
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
    authority_scope: str

    def validate(
        self,
        request: (
            EngineeringEvidenceValidationRequest
            | EngineeringRepairValidationRequest
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
        try:
            _require_validator_registration_unchanged(registration)
        except EvidenceValidationError as exc:
            raise EvidenceValidationError(
                str(exc),
                reason_code=(
                    exc.reason_code
                    or "validator_protocol_or_identity_mismatch"
                ),
            ) from exc

    def _authorized_registration(
        self,
        *,
        validator_id: str,
        domain: str,
    ) -> Any:
        registration = self._sealed_registration(
            validator_id=validator_id,
            domain=domain,
        )
        self._require_unchanged(registration)
        return registration

    def _sealed_registration(
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
                "no registered validator authorizes this evidence domain",
                reason_code="validator_absent_or_unregistered",
            )
        return registration

    def validate(
        self,
        request: (
            EngineeringEvidenceValidationRequest
            | EngineeringRepairValidationRequest
            | EvidenceValidationRequest
            | ExternalChangeValidationRequest
        ),
    ) -> tuple[ValidatedEvidence, ValidationTrace]:
        registration = self._authorized_registration(
            validator_id=request.validator_id,
            domain=request.domain,
        )
        if isinstance(request, EngineeringRepairValidationRequest):
            expected_scope = (
                "fixture_only" if request.engineering_fixture else "production"
            )
            implementation_path = registration.integrity.implementation_path
            production_root = Path(__file__).resolve().parents[1]
            try:
                implementation_path.relative_to(production_root)
                production_path = True
            except ValueError:
                production_path = False
            if (
                registration.integrity.authority_scope != expected_scope
                or (expected_scope == "production" and not production_path)
            ):
                raise EvidenceValidationError(
                    "Repair validator authority scope differs from the request",
                    reason_code="validator_protocol_or_identity_mismatch",
                )
        try:
            result = registration.validate(request)
            if not isinstance(result, ValidatedEvidence):
                raise EvidenceValidationError(
                    "validator returned an untyped result",
                    reason_code="partial_validator_result",
                )
            opened = sum(artifact.was_read for artifact in request.artifacts)
            if opened != len(request.artifacts):
                raise EvidenceValidationError(
                    "validator did not inspect every declared artifact",
                    reason_code="declared_artifact_absent_drifted_or_unopened",
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
                "validator protocol requirement is invalid",
                reason_code="validator_protocol_or_identity_mismatch",
            )
        registration = self._authorized_registration(
            validator_id=validator_id,
            domain=domain,
        )
        if registration.integrity.protocol != protocol:
            raise EvidenceValidationError(
                "registered validator protocol differs from the required capability",
                reason_code="validator_protocol_or_identity_mismatch",
            )

    def require_plannable_protocol(
        self,
        *,
        validator_id: str,
        domain: str,
        protocol: str,
    ) -> None:
        """Check immutable registration metadata without granting execution.

        Two-phase workflows use this only to construct a validation plan.  A
        later ``validate`` call still performs the full implementation and
        transitive-closure check both before and after dispatch.  This method
        therefore cannot authorize evidence or replace that boundary.
        """

        if type(protocol) is not str or not protocol or not protocol.isascii():
            raise EvidenceValidationError(
                "validator protocol requirement is invalid",
                reason_code="validator_protocol_or_identity_mismatch",
            )
        registration = self._sealed_registration(
            validator_id=validator_id,
            domain=domain,
        )
        if registration.integrity.protocol != protocol:
            raise EvidenceValidationError(
                "registered validator protocol differs from the required capability",
                reason_code="validator_protocol_or_identity_mismatch",
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


ENGINEERING_REPAIR_FIXTURE_PROTOCOL = "engineering_repair_fixture.v1"
ENGINEERING_REPAIR_FIXTURE_VALIDATOR_ID = validator_identity(
    protocol=ENGINEERING_REPAIR_FIXTURE_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION
    ),
)


class EngineeringRepairFixtureValidator:
    """Fixture-only validator for independently dispatched Repair evidence."""

    validator_id = ENGINEERING_REPAIR_FIXTURE_VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_IMPLEMENTATION
    protocol = ENGINEERING_REPAIR_FIXTURE_PROTOCOL
    authority_scope = "fixture_only"

    def validate(
        self,
        request: EngineeringRepairValidationRequest,
    ) -> ValidatedEvidence:
        if (
            not isinstance(request, EngineeringRepairValidationRequest)
            or not request.engineering_fixture
            or request.domain != "engineering"
        ):
            raise EvidenceValidationError(
                "engineering Repair validator is fixture-only"
            )
        by_name = {artifact.output_name: artifact for artifact in request.artifacts}
        if len(by_name) != len(request.artifacts):
            raise EvidenceValidationError(
                "engineering Repair artifact roles are duplicated"
            )
        plan_artifact = by_name.get("validation_plan")
        result_name = (
            "semantic_change_case"
            if request.verification_kind == "semantic_change"
            else "validation_result"
        )
        result_artifact = by_name.get(result_name)
        if plan_artifact is None or result_artifact is None:
            raise EvidenceValidationError(
                "engineering Repair plan or result is absent"
            )
        try:
            plan = parse_canonical(plan_artifact.read_bytes())
            result = parse_canonical(result_artifact.read_bytes())
        except (TypeError, ValueError) as exc:
            raise EvidenceValidationError(
                "engineering Repair fixture evidence is not canonical"
            ) from exc
        binding = _thaw_canonical(request.binding)
        roles = None if not isinstance(plan, Mapping) else plan.get("artifact_roles")
        expected_roles = [
            {"output_name": name, "sha256": artifact.sha256}
            for name, artifact in sorted(by_name.items())
            if name != "validation_plan"
        ]
        if (
            not isinstance(plan, Mapping)
            or set(plan)
            != {
                "artifact_roles",
                "binding_sha256",
                "protocol",
                "schema",
                "validator_id",
                "verification_kind",
            }
            or plan.get("schema") != "engineering_repair_validation_plan.v1"
            or plan.get("validator_id") != self.validator_id
            or plan.get("protocol") != self.protocol
            or plan.get("verification_kind") != request.verification_kind
            or plan.get("binding_sha256")
            != sha256(canonical_bytes(binding)).hexdigest()
            or roles != expected_roles
        ):
            raise EvidenceValidationError(
                "engineering Repair fixture plan differs from its request"
            )
        if request.verification_kind == "inventory":
            context = binding.get("context")
            if not isinstance(context, Mapping):
                raise EvidenceValidationError(
                    "engineering Repair fixture inventory context is absent"
                )
            try:
                inventory = normalize_repair_inventory_facts(
                    result,
                    accepted_attempts=context.get("repair_attempts", ()),
                    current_basis_hash=str(
                        context.get("current_basis_hash")
                    ),
                    information_set_hash=str(
                        context.get("information_set_hash")
                    ),
                    opened_result_artifact_hashes=tuple(
                        sorted(
                            artifact.sha256
                            for name, artifact in by_name.items()
                            if name != "validation_plan"
                        )
                    ),
                )
            except (
                RepairDispositionInventoryError,
                TypeError,
                ValueError,
            ) as exc:
                raise EvidenceValidationError(str(exc)) from exc
            for artifact in by_name.values():
                artifact.read_bytes()
            return ValidatedEvidence(
                verdict="passed",
                measurement_artifact_hashes=tuple(
                    sorted(
                        artifact.sha256
                        for name, artifact in by_name.items()
                        if name != "validation_plan"
                    )
                ),
                artifact_roles=tuple(
                    (name, artifact.sha256)
                    for name, artifact in by_name.items()
                ),
                facts={"binding": binding, **inventory},
                scientific_eligible=False,
                candidate_eligible=False,
                release_eligible=False,
            )
        if request.verification_kind == "semantic_change":
            binding_context = binding.get("context")
            try:
                semantic_case = normalize_semantic_change_case(result)
                if not isinstance(binding_context, Mapping):
                    raise RepairDispositionCaseError(
                        "semantic-change fixture context is absent"
                    )
                expected_facts = semantic_change_facts(
                    semantic_case,
                    current_basis_hash=str(
                        binding_context.get("current_basis_hash")
                    ),
                    accepted_attempt_head_record_id=binding_context.get(
                        "accepted_attempt_head_record_id"
                    ),
                    repair_validation_observation_head=binding_context.get(
                        "repair_validation_observation_head"
                    ),
                )
            except (RepairDispositionCaseError, TypeError, ValueError) as exc:
                raise EvidenceValidationError(str(exc)) from exc
            expected_context_case = {
                "changed_dimensions": binding_context.get(
                    "changed_dimensions"
                ),
                "correction_artifact_hashes": binding_context.get(
                    "correction_artifact_hashes"
                ),
                "protected_semantic_dimensions": binding_context.get(
                    "protected_semantic_dimensions"
                ),
                "rationale_evidence_hashes": binding_context.get(
                    "rationale_evidence_hashes"
                ),
                "schema": "engineering_semantic_change_case.v1",
            }
            if semantic_case != expected_context_case:
                raise EvidenceValidationError(
                    "semantic-change fixture case differs from authority"
                )
            role_pairs = tuple(
                (name, artifact.sha256) for name, artifact in by_name.items()
            )
            for artifact in by_name.values():
                artifact.read_bytes()
            return ValidatedEvidence(
                verdict="passed",
                measurement_artifact_hashes=tuple(
                    artifact.sha256
                    for name, artifact in by_name.items()
                    if name != "validation_plan"
                ),
                artifact_roles=role_pairs,
                facts={"binding": binding, **expected_facts},
                scientific_eligible=False,
                candidate_eligible=False,
                release_eligible=False,
            )
        if request.verification_kind == "candidate":
            if (
                not isinstance(result, Mapping)
                or set(result)
                != {
                    "failure_observed_after_change",
                    "material_change_observed",
                    "measurement_complete",
                    "observed_context",
                    "schema",
                    "support_artifact_hashes",
                }
                or result.get("schema")
                != "engineering_repair_candidate_fixture_measurement.v1"
                or result.get("observed_context") != binding.get("context")
                or type(result.get("failure_observed_after_change")) is not bool
                or type(result.get("material_change_observed")) is not bool
                or type(result.get("measurement_complete")) is not bool
            ):
                raise EvidenceValidationError(
                    "engineering Repair candidate fixture measurement is invalid"
                )
            support_hashes = sorted(
                artifact.sha256
                for name, artifact in by_name.items()
                if name.startswith("support:")
            )
            if result.get("support_artifact_hashes") != support_hashes:
                raise EvidenceValidationError(
                    "engineering Repair candidate fixture support differs"
                )
            for name, artifact in by_name.items():
                if name not in {"validation_plan", "validation_result"}:
                    artifact.read_bytes()
            if not result["measurement_complete"]:
                verdict = "not_evaluable"
                facts = {
                    "cause_resolved": None,
                    "failure_reproduced": None,
                    "material_change": None,
                    "mode": "not_evaluable",
                    "new_failure_manifest_hash": None,
                    "reason_code": "fixture_measurement_inconclusive",
                }
            elif not result["material_change_observed"]:
                verdict = "failed"
                facts = {
                    "cause_resolved": None,
                    "failure_reproduced": None,
                    "material_change": False,
                    "mode": "invalid_change",
                    "new_failure_manifest_hash": None,
                    "reason_code": "fixture_no_material_change",
                }
            elif result["failure_observed_after_change"]:
                verdict = "passed"
                facts = {
                    "cause_resolved": False,
                    "failure_reproduced": True,
                    "material_change": True,
                    "mode": "failure_reproduced",
                    "new_failure_manifest_hash": None,
                    "reason_code": None,
                }
            else:
                verdict = "passed"
                facts = {
                    "cause_resolved": True,
                    "failure_reproduced": False,
                    "material_change": True,
                    "mode": "repaired",
                    "new_failure_manifest_hash": None,
                    "reason_code": None,
                }
            return ValidatedEvidence(
                verdict=verdict,
                measurement_artifact_hashes=tuple(
                    artifact.sha256
                    for name, artifact in by_name.items()
                    if name != "validation_plan"
                ),
                artifact_roles=tuple(
                    (name, artifact.sha256) for name, artifact in by_name.items()
                ),
                facts={"binding": binding, **facts},
                scientific_eligible=False,
                candidate_eligible=False,
                release_eligible=False,
            )
        if (
            not isinstance(result, Mapping)
            or set(result)
            != {
                "disposition_case",
                "facts",
                "observed_context",
                "schema",
                "semantic_change_receipt_hash",
                "support_artifact_hashes",
                "verification_kind",
            }
            or result.get("schema") != "engineering_repair_fixture_result.v1"
            or result.get("verification_kind") != request.verification_kind
            or result.get("observed_context") != binding.get("context")
        ):
            raise EvidenceValidationError(
                "engineering Repair fixture result differs from authority"
            )
        support_hashes = sorted(
            artifact.sha256
            for name, artifact in by_name.items()
            if name.startswith("support:")
        )
        if result.get("support_artifact_hashes") != support_hashes:
            raise EvidenceValidationError(
                "engineering Repair fixture support differs"
            )
        for name, artifact in by_name.items():
            if name not in {"validation_plan", "validation_result"}:
                artifact.read_bytes()
        context = binding.get("context")
        facts = result.get("facts")
        if not isinstance(context, dict) or not isinstance(facts, Mapping):
            raise EvidenceValidationError(
                "engineering Repair fixture context is invalid"
            )
        if request.verification_kind != "attempt":
            raise EvidenceValidationError(
                "engineering Repair fixture has no generic terminal authority"
            )
        outcome = context.get("outcome")
        expected_facts = {
            "cause_resolved": outcome == "repaired",
            "failure_reproduced": outcome == "failed",
            "material_change": True,
        }
        if dict(facts) != expected_facts:
            raise EvidenceValidationError(
                "engineering Repair fixture facts were not recomputed"
            )
        role_pairs = tuple(
            (name, artifact.sha256) for name, artifact in by_name.items()
        )
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=tuple(
                artifact.sha256
                for name, artifact in by_name.items()
                if name != "validation_plan"
            ),
            artifact_roles=role_pairs,
            facts={"binding": binding, **expected_facts},
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
    "ENGINEERING_REPAIR_FIXTURE_PROTOCOL",
    "ENGINEERING_REPAIR_FIXTURE_VALIDATOR_ID",
    "ENGINEERING_RUNTIME_PLAN_HASH",
    "ENGINEERING_VALIDATOR_ID",
    "EngineeringFixtureValidator",
    "EngineeringRepairFixtureValidator",
    "EngineeringRepairValidationRequest",
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
