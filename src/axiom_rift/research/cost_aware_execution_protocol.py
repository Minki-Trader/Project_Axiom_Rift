"""Immutable paired-policy protocol for a historical execution replay.

The historical family contains exactly two policies: an unconditional next-open
control and a causal spread-abstention target.  This module binds those members
to their prospective Executable identities and freezes the scientific-v2
criteria and concurrent-family inference boundary.  Historical exposure count
is retained only as audit context and never enters either family adjustment.

The protocol definition is deliberately data-only.  It contains no callback,
module path, implementation locator, or other ambient execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.adjudication import (
    MULTIPLICITY_CRITERION_IDS,
    RISK_DIAGNOSTIC_CRITERION_IDS,
    VALIDITY_METRICS,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilySpec,
    historical_family_from_manifest,
)
from axiom_rift.research.scientific_study import (
    PLANNED_CLAIMS,
    discovery_criteria,
)
from axiom_rift.research.scientific_trace import (
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
)


COST_AWARE_EXECUTION_PROTOCOL_ID = (
    "cost_aware_execution.paired_policy.fixed_hold_replay.v1"
)
COST_AWARE_EXECUTION_PROTOCOL_DEFINITION_SCHEMA = (
    "cost_aware_execution_protocol_definition.v1"
)
COST_AWARE_EXECUTION_MEMBER_BINDING_SCHEMA = (
    "cost_aware_execution_member_binding.v1"
)
COST_AWARE_EXECUTION_PRIMARY_CONTROL_SCHEMA = (
    "cost_aware_execution_primary_control.v1"
)
COST_AWARE_EXECUTION_INFERENCE_BOUNDARY_SCHEMA = (
    "cost_aware_execution_inference_boundary.v1"
)
COST_AWARE_EXECUTION_SUBJECT_INFERENCE_FAMILY_SCHEMA = (
    "cost_aware_execution_subject_inference_family.v1"
)
COST_AWARE_EXECUTION_ADJUDICATION_PROFILE_SCHEMA = (
    "scientific_adjudication_profile.v1"
)
COST_AWARE_EXECUTION_MULTIPLICITY_METHOD = (
    "synchronized_max_moving_block_familywise.v1"
)
COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY = (
    "context_only_never_adjustment_factor"
)
COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 526
COST_AWARE_EXECUTION_ALPHA_PPM = 100_000
COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES = 41_999
COST_AWARE_EXECUTION_BLOCK_LENGTHS = (5, 10, 20)
COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM = 990_000
COST_AWARE_EXECUTION_BASE_SEED = 612_337_279
COST_AWARE_EXECUTION_HISTORICAL_FAMILY_ID = (
    "historical-family:"
    "4aaecbfcb74a8f0e764124fcfbb7760f366f0dd2efa4f4f9e268cb8b8cf42583"
)

COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID = (
    "executable:4906f193080ed2dab041aaa26420b8dcceb1df606922f1b14bc1723ef439df2f"
)
COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID = (
    "executable:33ad1cd7b5eabe24d65fad22be9757826a19fa20f6a2e16f871c6ff32a68a9d3"
)
COST_AWARE_EXECUTION_CONTROL_DELTA_METRIC = (
    "execution_control_delta_net_profit_micropoints"
)
COST_AWARE_EXECUTION_CONTROL_PVALUE_METRIC = (
    "execution_control_pvalue_upper_ppm"
)


class CostAwareExecutionProtocolError(ValueError):
    """The exact paired-policy protocol definition is invalid."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise CostAwareExecutionProtocolError(
            f"{name} must be non-empty ASCII"
        )
    return value


def _executable_id(name: str, value: object) -> str:
    if type(value) is not str or not value.isascii():
        raise CostAwareExecutionProtocolError(
            f"{name} must be executable:<lowercase-sha256>"
        )
    digest = value.removeprefix("executable:")
    if (
        digest == value
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise CostAwareExecutionProtocolError(
            f"{name} must be executable:<lowercase-sha256>"
        )
    return value


_CRITERION_EVIDENCE_MODES = {
    "A01-minimum-trades": "cost_and_execution",
    "A02-positive-density": "cost_and_execution",
    "A03-profit-day-concentration": "cost_and_execution",
    "B01-positive-native-cost": "cost_and_execution",
    "B02-fold-profit-factor": "cost_and_execution",
    "B03-slippage-stress": "sensitivity_or_stress",
    "B04-monthly-realized-drawdown-share": "cost_and_execution",
    "C01-feature-prefix-invariance": "causal_contrast",
    "C02-decision-append-invariance": "causal_contrast",
    "C03-decision-time-causality": "causal_contrast",
    "C04-resolved-cost": "cost_and_execution",
    "C05-finite-metrics": "causal_contrast",
    "D03-primary-control": "causal_contrast",
    "D04-primary-control-uncertainty": "causal_contrast",
    "E01-familywise-selection": "temporal_stability",
    "F01-evaluable-folds": "temporal_stability",
    "F02-winning-folds": "temporal_stability",
    "F03-positive-regimes": "temporal_stability",
}


def _decision_role(criterion: dict[str, object]) -> str:
    criterion_id = criterion["criterion_id"]
    metric = criterion["metric"]
    if metric in VALIDITY_METRICS:
        return "validity"
    if criterion_id in MULTIPLICITY_CRITERION_IDS:
        return "multiplicity"
    if criterion_id in RISK_DIAGNOSTIC_CRITERION_IDS:
        return "risk_diagnostic"
    return "component"


def cost_aware_execution_criteria() -> tuple[dict[str, object], ...]:
    """Return a fresh copy of the exact 18 scientific-v2 criteria."""

    legacy = discovery_criteria(
        control_delta_metric=COST_AWARE_EXECUTION_CONTROL_DELTA_METRIC,
        control_pvalue_metric=COST_AWARE_EXECUTION_CONTROL_PVALUE_METRIC,
        include_opposite_sign=False,
    )
    by_id = {item["criterion_id"]: item for item in legacy}
    if set(by_id) != set(_CRITERION_EVIDENCE_MODES) or len(legacy) != 18:
        raise RuntimeError("cost-aware execution criterion inventory drifted")
    criteria = tuple(
        {
            **item,
            "decision_role": _decision_role(item),
            "evidence_mode": _CRITERION_EVIDENCE_MODES[item["criterion_id"]],
        }
        for item in sorted(
            legacy,
            key=lambda value: (value["claim_id"], value["criterion_id"]),
        )
    )
    claims = tuple(sorted({item["claim_id"] for item in criteria}))
    modes = tuple(sorted({item["evidence_mode"] for item in criteria}))
    if claims != PLANNED_CLAIMS or modes != (
        "causal_contrast",
        "cost_and_execution",
        "sensitivity_or_stress",
        "temporal_stability",
    ):
        raise RuntimeError("cost-aware execution scientific surface drifted")
    return criteria


COST_AWARE_EXECUTION_REPLAY_CRITERIA = cost_aware_execution_criteria()
COST_AWARE_EXECUTION_REPLAY_CLAIMS = PLANNED_CLAIMS
COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
    "temporal_stability",
)


@dataclass(frozen=True, slots=True)
class CostAwareExecutionMemberBinding:
    """One explicit historical-to-prospective policy role binding."""

    role: str
    execution_policy: str
    configuration_id: str
    historical_ordinal: int
    historical_executable_id: str
    prospective_executable_id: str

    def manifest(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "execution_policy": self.execution_policy,
            "historical_executable_id": self.historical_executable_id,
            "historical_ordinal": self.historical_ordinal,
            "prospective_executable_id": self.prospective_executable_id,
            "role": self.role,
            "schema": COST_AWARE_EXECUTION_MEMBER_BINDING_SCHEMA,
        }


def _member_bindings(
    *,
    historical_family: HistoricalFamilySpec,
    prospective_control_executable_id: str,
    prospective_target_executable_id: str,
) -> tuple[CostAwareExecutionMemberBinding, ...]:
    prospective_by_historical = {
        COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID: (
            "control",
            prospective_control_executable_id,
        ),
        COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID: (
            "target",
            prospective_target_executable_id,
        ),
    }
    if (
        not isinstance(historical_family, HistoricalFamilySpec)
        or historical_family.identity
        != COST_AWARE_EXECUTION_HISTORICAL_FAMILY_ID
    ):
        raise RuntimeError("cost-aware historical family authority drifted")
    bindings: list[CostAwareExecutionMemberBinding] = []
    for member in historical_family.members:
        try:
            role, prospective_id = prospective_by_historical[
                member.historical_reference_executable_id
            ]
        except KeyError as exc:
            raise RuntimeError(
                "historical family contains an unregistered policy member"
            ) from exc
        parameters = member.parameter_values()
        policy = parameters.get("execution_policy")
        if type(policy) is not str or not policy.isascii():
            raise RuntimeError("historical execution policy is invalid")
        bindings.append(
            CostAwareExecutionMemberBinding(
                role=role,
                execution_policy=policy,
                configuration_id=member.configuration_id,
                historical_ordinal=member.ordinal,
                historical_executable_id=(
                    member.historical_reference_executable_id
                ),
                prospective_executable_id=prospective_id,
            )
        )
    result = tuple(sorted(bindings, key=lambda item: item.historical_ordinal))
    if (
        len(result) != 2
        or {item.role for item in result} != {"control", "target"}
        or {item.execution_policy for item in result}
        != {"unconditional_next_open", "causal_spread_abstention"}
    ):
        raise RuntimeError("historical paired-policy family drifted")
    return result


def _family_registration_hash(
    *,
    family_id: str,
    ordered_member_ids: tuple[str, ...],
) -> str:
    """Mirror the scientific-v2 canonical registration without importing it."""

    if (
        type(family_id) is not str
        or not family_id
        or not family_id.isascii()
        or type(ordered_member_ids) is not tuple
        or not ordered_member_ids
        or any(
            type(item) is not str or not item or not item.isascii()
            for item in ordered_member_ids
        )
        or len(ordered_member_ids) != len(set(ordered_member_ids))
    ):
        raise CostAwareExecutionProtocolError(
            "multiplicity family registration is invalid"
        )
    return canonical_digest(
        domain="scientific-v2-multiplicity-family",
        payload={
            "alpha_ppm": COST_AWARE_EXECUTION_ALPHA_PPM,
            "family_id": family_id,
            "family_size": len(ordered_member_ids),
            "method": COST_AWARE_EXECUTION_MULTIPLICITY_METHOD,
            "ordered_member_ids": list(ordered_member_ids),
            "schema": "scientific_multiplicity_family_registration.v1",
        },
    )


def _multiplicity_registration(
    *,
    criterion_id: str,
    family_id: str,
    member_id: str,
    ordered_member_ids: tuple[str, ...],
) -> dict[str, object]:
    if member_id not in ordered_member_ids:
        raise CostAwareExecutionProtocolError(
            "multiplicity member is outside its exact family"
        )
    return {
        "alpha_ppm": COST_AWARE_EXECUTION_ALPHA_PPM,
        "criterion_id": criterion_id,
        "family_id": family_id,
        "family_registration_hash": _family_registration_hash(
            family_id=family_id,
            ordered_member_ids=ordered_member_ids,
        ),
        "family_size": len(ordered_member_ids),
        "member_id": member_id,
        "method": COST_AWARE_EXECUTION_MULTIPLICITY_METHOD,
        "ordered_member_ids": list(ordered_member_ids),
    }


@dataclass(frozen=True, slots=True)
class CostAwareExecutionProtocolDefinition:
    """One corrected prospective pair bound to an exact historical family."""

    historical_family: HistoricalFamilySpec
    prospective_control_executable_id: str
    prospective_target_executable_id: str
    identity: str = field(init=False)
    prospective_family_id: str = field(init=False)
    primary_control_contrast_id: str = field(init=False)
    primary_control_family_id: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.historical_family, HistoricalFamilySpec)
            or self.historical_family.identity
            != COST_AWARE_EXECUTION_HISTORICAL_FAMILY_ID
        ):
            raise CostAwareExecutionProtocolError(
                "protocol requires the exact Writer-bound historical family"
            )
        control = _executable_id(
            "prospective_control_executable_id",
            self.prospective_control_executable_id,
        )
        target = _executable_id(
            "prospective_target_executable_id",
            self.prospective_target_executable_id,
        )
        if control == target:
            raise CostAwareExecutionProtocolError(
                "prospective control and target Executable ids must differ"
            )
        bindings = self.member_bindings
        family_digest = canonical_digest(
            domain="cost-aware-execution-prospective-policy-family",
            payload={
                "historical_family_identity": self.historical_family.identity,
                "ordered_historical_member_ids": [
                    item.historical_executable_id for item in bindings
                ],
                "protocol_id": COST_AWARE_EXECUTION_PROTOCOL_ID,
            },
        )
        object.__setattr__(self, "prospective_family_id", f"family:{family_digest}")
        contrast_digest = canonical_digest(
            domain="cost-aware-execution-primary-control-contrast",
            payload={
                "control_historical_executable_id": (
                    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID
                ),
                "protocol_id": COST_AWARE_EXECUTION_PROTOCOL_ID,
                "schema": COST_AWARE_EXECUTION_PRIMARY_CONTROL_SCHEMA,
                "target_historical_executable_id": (
                    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
                ),
            },
        )
        contrast_id = f"contrast:{contrast_digest}"
        object.__setattr__(self, "primary_control_contrast_id", contrast_id)
        control_family_digest = canonical_digest(
            domain="cost-aware-execution-primary-control-family",
            payload={
                "ordered_member_ids": [contrast_id],
                "protocol_id": COST_AWARE_EXECUTION_PROTOCOL_ID,
            },
        )
        object.__setattr__(
            self,
            "primary_control_family_id",
            f"family:{control_family_digest}",
        )
        definition_digest = canonical_digest(
            domain="cost-aware-execution-protocol-definition",
            payload=self.manifest(),
        )
        object.__setattr__(
            self,
            "identity",
            f"cost-aware-execution-definition:{definition_digest}",
        )

    @property
    def protocol_id(self) -> str:
        return COST_AWARE_EXECUTION_PROTOCOL_ID

    @property
    def family(self):
        """Expose the exact family through the protocol-neutral replay port."""

        return self.historical_family

    @property
    def member_bindings(self) -> tuple[CostAwareExecutionMemberBinding, ...]:
        return _member_bindings(
            historical_family=self.historical_family,
            prospective_control_executable_id=(
                self.prospective_control_executable_id
            ),
            prospective_target_executable_id=(
                self.prospective_target_executable_id
            ),
        )

    @property
    def prospective_executable_ids(self) -> tuple[str, ...]:
        """Return the pair in immutable historical-member ordinal order."""

        return tuple(
            item.prospective_executable_id for item in self.member_bindings
        )

    @property
    def criteria(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in COST_AWARE_EXECUTION_REPLAY_CRITERIA)

    @property
    def planned_claims(self) -> tuple[str, ...]:
        return COST_AWARE_EXECUTION_REPLAY_CLAIMS

    @property
    def evidence_modes(self) -> tuple[str, ...]:
        return COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES

    def manifest(self) -> dict[str, object]:
        return {
            "criteria": [dict(item) for item in self.criteria],
            "evidence_modes": list(self.evidence_modes),
            "historical_family": self.historical_family.manifest(),
            "inference": {
                "alpha_ppm": COST_AWARE_EXECUTION_ALPHA_PPM,
                "base_seed": COST_AWARE_EXECUTION_BASE_SEED,
                "block_lengths": list(COST_AWARE_EXECUTION_BLOCK_LENGTHS),
                "bootstrap_samples": COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES,
                "historical_context_adjustment_authority": (
                    COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY
                ),
                "original_family_end_global_exposure_count": (
                    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
                ),
                "method": COST_AWARE_EXECUTION_MULTIPLICITY_METHOD,
                "monte_carlo_confidence_ppm": (
                    COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM
                ),
                "primary_control_contrast_family_id": (
                    self.primary_control_family_id
                ),
                "primary_control_contrast_family_size": 1,
                "schema": COST_AWARE_EXECUTION_INFERENCE_BOUNDARY_SCHEMA,
                "selection_family_id": self.prospective_family_id,
                "selection_family_size": 2,
            },
            "members": [item.manifest() for item in self.member_bindings],
            "planned_claims": list(self.planned_claims),
            "primary_control": {
                "control_historical_executable_id": (
                    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID
                ),
                "control_prospective_executable_id": (
                    self.prospective_control_executable_id
                ),
                "contrast_id": self.primary_control_contrast_id,
                "schema": COST_AWARE_EXECUTION_PRIMARY_CONTROL_SCHEMA,
                "target_historical_executable_id": (
                    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
                ),
                "target_prospective_executable_id": (
                    self.prospective_target_executable_id
                ),
            },
            "prospective_family_id": self.prospective_family_id,
            "prospective_control_executable_id": (
                self.prospective_control_executable_id
            ),
            "prospective_target_executable_id": (
                self.prospective_target_executable_id
            ),
            "protocol_id": COST_AWARE_EXECUTION_PROTOCOL_ID,
            "schema": COST_AWARE_EXECUTION_PROTOCOL_DEFINITION_SCHEMA,
        }


def cost_aware_execution_subject_inference_families(
    definition: CostAwareExecutionProtocolDefinition,
    subject_executable_id: str,
) -> tuple[dict[str, object], ...]:
    """Return the two exact subject-level inference families.

    D04 evaluates one preregistered paired contrast, so its hypothesis family
    has one member even though the contrast consumes two policy paths.  E01
    performs selection across the two concurrently registered policy members.
    """

    if not isinstance(definition, CostAwareExecutionProtocolDefinition):
        raise CostAwareExecutionProtocolError(
            "subject inference families require a typed protocol definition"
        )
    subject = _executable_id(
        "subject_executable_id",
        subject_executable_id,
    )
    if subject not in definition.prospective_executable_ids:
        raise CostAwareExecutionProtocolError(
            "subject Executable is outside the exact prospective pair"
        )
    return (
        {
            "criterion_id": "D04-primary-control-uncertainty",
            "family_id": definition.primary_control_family_id,
            "family_size": 1,
            "inference_role": "primary_control_contrast",
            "member_id": definition.primary_control_contrast_id,
            "ordered_member_ids": [definition.primary_control_contrast_id],
            "schema": COST_AWARE_EXECUTION_SUBJECT_INFERENCE_FAMILY_SCHEMA,
        },
        {
            "criterion_id": "E01-familywise-selection",
            "family_id": definition.prospective_family_id,
            "family_size": 2,
            "inference_role": "concurrent_policy_selection",
            "member_id": subject,
            "ordered_member_ids": sorted(
                definition.prospective_executable_ids
            ),
            "schema": COST_AWARE_EXECUTION_SUBJECT_INFERENCE_FAMILY_SCHEMA,
        },
    )


def cost_aware_execution_multiplicity_registrations(
    definition: CostAwareExecutionProtocolDefinition,
    subject_executable_id: str,
) -> tuple[dict[str, object], ...]:
    """Project scientific-v2 registrations from the exact subject families."""

    registrations = []
    for family in cost_aware_execution_subject_inference_families(
        definition,
        subject_executable_id,
    ):
        registrations.append(
            _multiplicity_registration(
                criterion_id=family["criterion_id"],
                family_id=family["family_id"],
                member_id=family["member_id"],
                ordered_member_ids=tuple(family["ordered_member_ids"]),
            )
        )
    return tuple(registrations)


def _proof_requirements(
    output_names: Mapping[str, str],
) -> tuple[dict[str, str], ...]:
    if not isinstance(output_names, Mapping):
        raise CostAwareExecutionProtocolError(
            "cost-aware execution output_names must be a mapping"
        )
    try:
        trace_output = _ascii(
            "cost-aware execution trace output_name",
            output_names["trace"],
        )
        calculation_output = _ascii(
            "cost-aware execution calculation output_name",
            output_names["calculation"],
        )
    except KeyError as exc:
        raise CostAwareExecutionProtocolError(
            "cost-aware execution proof output is not preregistered"
        ) from exc
    if trace_output == calculation_output:
        raise CostAwareExecutionProtocolError(
            "trace and calculation proofs require distinct outputs"
        )
    return tuple(
        sorted(
            (
                {
                    "artifact_schema": artifact_schema,
                    "evidence_mode": mode,
                    "output_name": output_name,
                    "proof_kind": proof_kind,
                }
                for mode in COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES
                for proof_kind, artifact_schema, output_name in (
                    (
                        ATOMIC_TRACE_PROOF_KIND,
                        SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
                        trace_output,
                    ),
                    (
                        CALCULATION_PROOF_KIND,
                        SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
                        calculation_output,
                    ),
                )
            ),
            key=lambda item: (
                item["evidence_mode"],
                item["proof_kind"],
                item["output_name"],
            ),
        )
    )


def build_cost_aware_execution_validation_plan(
    *,
    definition: CostAwareExecutionProtocolDefinition,
    mission_id: str,
    executable_id: str,
    output_names: Mapping[str, str],
) -> dict[str, object]:
    """Build one subject-bound, discovery-only scientific-v2 plan."""

    if not isinstance(definition, CostAwareExecutionProtocolDefinition):
        raise CostAwareExecutionProtocolError(
            "validation plan requires a typed protocol definition"
        )
    mission = _ascii("cost-aware execution mission_id", mission_id)
    subject = _executable_id("cost-aware execution executable_id", executable_id)
    registrations = cost_aware_execution_multiplicity_registrations(
        definition,
        subject,
    )
    profile = {
        "decisive_risk_criterion_ids": [],
        "multiplicity": list(registrations),
        "promotion_criterion_ids": [],
        "schema": COST_AWARE_EXECUTION_ADJUDICATION_PROFILE_SCHEMA,
    }
    from axiom_rift.research.validation_v2 import build_validation_plan_v2

    return build_validation_plan_v2(
        mission_id=mission,
        executable_id=subject,
        evidence_depth="discovery",
        planned_claims=COST_AWARE_EXECUTION_REPLAY_CLAIMS,
        evidence_modes=COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES,
        criteria=COST_AWARE_EXECUTION_REPLAY_CRITERIA,
        adjudication_profile=profile,
        proof_requirements=_proof_requirements(output_names),
        candidate_eligible_on_pass=False,
        protocol_definition=definition.manifest(),
    )


def cost_aware_execution_protocol_definition(
    *,
    historical_family: HistoricalFamilySpec,
    prospective_control_executable_id: str,
    prospective_target_executable_id: str,
) -> CostAwareExecutionProtocolDefinition:
    """Bind one corrected prospective pair to the immutable protocol."""

    return CostAwareExecutionProtocolDefinition(
        historical_family=historical_family,
        prospective_control_executable_id=prospective_control_executable_id,
        prospective_target_executable_id=prospective_target_executable_id,
    )


def cost_aware_execution_protocol_definition_from_manifest(
    value: object,
) -> CostAwareExecutionProtocolDefinition:
    """Parse only the exact canonical definition admitted by this protocol."""

    if type(value) is not dict:
        raise CostAwareExecutionProtocolError(
            "cost-aware execution protocol definition must be an object"
        )
    try:
        normalized = parse_canonical(canonical_bytes(value))
    except (TypeError, ValueError) as exc:
        raise CostAwareExecutionProtocolError(
            "cost-aware execution protocol definition is not canonical"
        ) from exc
    if type(normalized) is not dict:
        raise CostAwareExecutionProtocolError(
            "cost-aware execution protocol definition is not an object"
        )
    try:
        historical_family = historical_family_from_manifest(
            normalized["historical_family"]
        )
        definition = cost_aware_execution_protocol_definition(
            historical_family=historical_family,
            prospective_control_executable_id=normalized[
                "prospective_control_executable_id"
            ],
            prospective_target_executable_id=normalized[
                "prospective_target_executable_id"
            ],
        )
    except (KeyError, TypeError, ValueError, CostAwareExecutionProtocolError) as exc:
        raise CostAwareExecutionProtocolError(
            "cost-aware execution prospective pair is invalid"
        ) from exc
    if canonical_bytes(normalized) != canonical_bytes(definition.manifest()):
        raise CostAwareExecutionProtocolError(
            "cost-aware execution protocol definition differs from authority"
        )
    return definition


__all__ = [
    "COST_AWARE_EXECUTION_ADJUDICATION_PROFILE_SCHEMA",
    "COST_AWARE_EXECUTION_ALPHA_PPM",
    "COST_AWARE_EXECUTION_BASE_SEED",
    "COST_AWARE_EXECUTION_BLOCK_LENGTHS",
    "COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES",
    "COST_AWARE_EXECUTION_CONTROL_DELTA_METRIC",
    "COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID",
    "COST_AWARE_EXECUTION_CONTROL_PVALUE_METRIC",
    "COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY",
    "COST_AWARE_EXECUTION_HISTORICAL_FAMILY_ID",
    "COST_AWARE_EXECUTION_INFERENCE_BOUNDARY_SCHEMA",
    "COST_AWARE_EXECUTION_MEMBER_BINDING_SCHEMA",
    "COST_AWARE_EXECUTION_MULTIPLICITY_METHOD",
    "COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM",
    "COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT",
    "COST_AWARE_EXECUTION_PRIMARY_CONTROL_SCHEMA",
    "COST_AWARE_EXECUTION_PROTOCOL_DEFINITION_SCHEMA",
    "COST_AWARE_EXECUTION_PROTOCOL_ID",
    "COST_AWARE_EXECUTION_REPLAY_CLAIMS",
    "COST_AWARE_EXECUTION_REPLAY_CRITERIA",
    "COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES",
    "COST_AWARE_EXECUTION_SUBJECT_INFERENCE_FAMILY_SCHEMA",
    "COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID",
    "CostAwareExecutionMemberBinding",
    "CostAwareExecutionProtocolDefinition",
    "CostAwareExecutionProtocolError",
    "build_cost_aware_execution_validation_plan",
    "cost_aware_execution_criteria",
    "cost_aware_execution_multiplicity_registrations",
    "cost_aware_execution_protocol_definition",
    "cost_aware_execution_protocol_definition_from_manifest",
    "cost_aware_execution_subject_inference_families",
]
