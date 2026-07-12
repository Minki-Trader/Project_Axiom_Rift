"""Production validation for subject-bound scientific measurements.

The validator consumes preregistered integer criteria and raw fixed-point
measurements.  It never accepts a caller-supplied verdict or check result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
)


SCIENTIFIC_VALIDATION_PLAN_SCHEMA = "scientific_validation_plan.v1"
SCIENTIFIC_MEASUREMENT_SCHEMA = "scientific_measurement.v1"
SCIENTIFIC_RESULT_SCHEMA = "scientific_job_evidence.v1"
SCIENTIFIC_VALIDATION_PROTOCOL = "scientific_discovery.v1"
SCIENTIFIC_VALIDATION_DOMAINS = frozenset({"scientific"})
SCIENTIFIC_CRITERION_OPERATORS = frozenset({"eq", "ge", "gt", "le", "lt"})

_PLAN_FIELDS = {
    "candidate_eligible_on_pass",
    "criteria",
    "evidence_depth",
    "evidence_modes",
    "executable_id",
    "mission_id",
    "planned_claims",
    "schema",
}
_CRITERION_FIELDS = {
    "claim_id",
    "criterion_id",
    "evidence_mode",
    "metric",
    "operator",
    "threshold",
}
_MEASUREMENT_FIELDS = {
    "claims",
    "evidence_depth",
    "evidence_modes",
    "evaluation_artifact_hash",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "schema",
}
_TREND_EVALUATION_FIELDS = {
    "claim_limits",
    "direction_metrics",
    "evaluable",
    "fold_metrics",
    "job_execution",
    "metrics",
    "regime_metrics",
    "schema",
    "selection_context",
    "selection_method",
    "session_metrics",
    "session_semantics",
    "subject_configuration_id",
    "subject_executable_id",
    "surface_artifact_hash",
    "surface_manifest_hash",
}
_RESULT_FIELDS = {
    "evidence_depth",
    "executable_id",
    "job_hash",
    "job_id",
    "mission_id",
    "observations",
    "schema",
}
_SCIENTIFIC_BINDING_FIELDS = {
    "evidence_depth",
    "evidence_modes",
    "planned_claims",
    "result_manifest_output",
    "validation_plan_hash",
    "validator_id",
}
_SCIENTIFIC_PREFLIGHT_BINDING_FIELDS = _SCIENTIFIC_BINDING_FIELDS | {
    "evaluation_schema"
}
_SCIENTIFIC_EVALUATION_PROFILES = {
    "composite_consensus_evaluation.v1": (12, 222),
    "composite_router_evaluation.v1": (12, 210),
    "cross_asset_downside_spillover_evaluation.v1": (12, 246),
    "cross_asset_relative_strength_evaluation.v1": (12, 234),
    "price_level_interaction_evaluation.v1": (12, 258),
    "post_break_interaction_evaluation.v1": (12, 270),
    "path_efficiency_evaluation.v1": (12, 282),
    "path_roughness_evaluation.v1": (12, 294),
    "shock_aftereffect_evaluation.v1": (12, 306),
    "shock_cluster_evaluation.v1": (12, 318),
    "nonlinear_interaction_evaluation.v1": (12, 330),
    "shock_level_interaction_evaluation.v1": (4, 334),
    "cyclical_phase_evaluation.v1": (6, 340),
    "cyclical_harmonic_evaluation.v1": (4, 344),
    "distribution_asymmetry_evaluation.v1": (12, 356),
    "distribution_asymmetry_evaluation.v2": (12, 368),
    "candle_geometry_evaluation.v1": (6, 374),
    "candle_geometry_evaluation.v2": (6, 380),
    "liquidity_supply_evaluation.v1": (4, 384),
    "liquidity_supply_evaluation.v2": (4, 388),
    "long_horizon_drift_evaluation.v1": (6, 394),
    "long_horizon_drift_evaluation.v2": (6, 400),
    "learned_state_evaluation.v1": (4, 404),
    "learned_state_evaluation.v2": (4, 408),
    "ordinal_transition_evaluation.v1": (6, 414),
    "ordinal_transition_evaluation.v2": (6, 420),
    "gap_recovery_evaluation.v1": (4, 424),
    "gap_recovery_evaluation.v2": (4, 428),
    "gap_recovery_evaluation.v3": (4, 432),
    "gap_recovery_evaluation.v4": (4, 436),
    "drawdown_state_evaluation.v1": (4, 440),
    "drawdown_state_evaluation.v2": (4, 444),
    "volatility_duration_evaluation.v1": (4, 448),
    "volatility_duration_evaluation.v2": (4, 452),
    "transition_mixture_evaluation.v1": (4, 456),
    "transition_mixture_evaluation.v2": (4, 460),
    "transition_mixture_evaluation.v3": (4, 464),
    "structural_break_evaluation.v1": (4, 468),
    "structural_break_evaluation.v2": (4, 472),
    "auction_location_evaluation.v1": (4, 476),
    "auction_location_evaluation.v2": (4, 480),
    "higher_order_volatility_evaluation.v1": (4, 484),
    "higher_order_volatility_evaluation.v2": (4, 488),
    "analog_state_evaluation.v1": (4, 492),
    "analog_state_evaluation.v2": (4, 496),
    "adaptive_lifecycle_evaluation.v1": (4, 500),
    "adaptive_lifecycle_evaluation.v2": (4, 504),
    "event_label_evaluation.v1": (4, 508),
    "path_occupancy_label_evaluation.v1": (2, 528),
    "fold_interaction_model_evaluation.v1": (2, 530),
    "volatility_clock_label_evaluation.v1": (2, 532),
    "volatility_stop_risk_evaluation.v1": (2, 534),
    "shadow_slot_lifecycle_evaluation.v1": (2, 536),
    "equity_premium_trade_evaluation.v1": (2, 538),
    "trend_regime_evaluation.v1": (2, 540),
    "dense_short_synthesis_evaluation.v1": (2, 542),
    "high_vol_dense_regime_evaluation.v1": (2, 544),
    "complementary_sleeve_evaluation.v1": (4, 512),
    "probability_calibration_evaluation.v1": (4, 516),
    "rank_bin_calibration_evaluation.v1": (4, 520),
    "cost_utility_objective_evaluation.v1": (4, 524),
    "cost_aware_execution_evaluation.v1": (2, 530),
    "reversion_discovery_evaluation.v1": (12, 54),
    "reversion_regime_followup_evaluation.v1": (12, 186),
    "session_inventory_discovery_evaluation.v1": (12, 114),
    "session_inventory_followup_evaluation.v1": (12, 162),
    "trend_discovery_evaluation.v3": (12, 42),
    "trend_null_followup_evaluation.v1": (12, 174),
    "volume_price_discovery_evaluation.v1": (12, 78),
    "volume_price_followup_evaluation.v1": (12, 126),
    "volatility_discovery_evaluation.v1": (12, 66),
    "volatility_regime_followup_evaluation.v1": (12, 198),
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EvidenceValidationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise EvidenceValidationError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _evaluation_profile(value: object) -> tuple[str, int, int]:
    schema = _ascii("scientific evaluation schema", value)
    profile = _SCIENTIFIC_EVALUATION_PROFILES.get(schema)
    if profile is None:
        raise EvidenceValidationError(
            "scientific evaluation schema is not registered"
        )
    context_count, total_exposures = profile
    return schema, context_count, total_exposures


def require_supported_evaluation_schema(value: object) -> str:
    """Require a complete validator profile before scientific engine work."""

    schema, _, _ = _evaluation_profile(value)
    return schema


def _sorted_ascii_list(name: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise EvidenceValidationError(f"{name} must be a non-empty sequence")
    normalized = tuple(_ascii(name, item) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise EvidenceValidationError(f"{name} must be sorted and unique")
    return normalized


def _plain(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    if isinstance(value, list):
        return [_plain(child) for child in value]
    return value


@dataclass(frozen=True, slots=True)
class _Criterion:
    criterion_id: str
    claim_id: str
    evidence_mode: str
    metric: str
    operator: str
    threshold: int

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.claim_id, self.criterion_id

    @property
    def metric_key(self) -> tuple[str, str]:
        return self.claim_id, self.metric

    def manifest(self) -> dict[str, str | int]:
        return {
            "claim_id": self.claim_id,
            "criterion_id": self.criterion_id,
            "evidence_mode": self.evidence_mode,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
        }


def _criterion(value: object) -> _Criterion:
    if not isinstance(value, Mapping) or set(value) != _CRITERION_FIELDS:
        raise EvidenceValidationError("scientific criterion schema is invalid")
    threshold = value["threshold"]
    if type(threshold) is not int:
        raise EvidenceValidationError("scientific criterion threshold must be an integer")
    operator = _ascii("criterion operator", value["operator"])
    if operator not in SCIENTIFIC_CRITERION_OPERATORS:
        raise EvidenceValidationError("scientific criterion operator is invalid")
    return _Criterion(
        criterion_id=_ascii("criterion_id", value["criterion_id"]),
        claim_id=_ascii("criterion claim_id", value["claim_id"]),
        evidence_mode=_ascii("criterion evidence_mode", value["evidence_mode"]),
        metric=_ascii("criterion metric", value["metric"]),
        operator=operator,
        threshold=threshold,
    )


def _criteria(
    value: object,
    *,
    claims: tuple[str, ...],
    modes: tuple[str, ...],
) -> tuple[_Criterion, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise EvidenceValidationError("scientific plan requires criteria")
    parsed = tuple(_criterion(item) for item in value)
    if tuple(item.sort_key for item in parsed) != tuple(
        sorted(item.sort_key for item in parsed)
    ):
        raise EvidenceValidationError("scientific criteria must be canonically ordered")
    criterion_ids = tuple(item.criterion_id for item in parsed)
    if len(set(criterion_ids)) != len(criterion_ids):
        raise EvidenceValidationError("scientific criterion identities must be unique")
    if {item.claim_id for item in parsed} != set(claims):
        raise EvidenceValidationError("scientific criteria do not cover every claim")
    if {item.evidence_mode for item in parsed} != set(modes):
        raise EvidenceValidationError("scientific criteria do not cover every evidence mode")
    metric_modes: dict[tuple[str, str], str] = {}
    for item in parsed:
        previous = metric_modes.setdefault(item.metric_key, item.evidence_mode)
        if previous != item.evidence_mode:
            raise EvidenceValidationError(
                "one raw metric cannot establish multiple evidence modes"
            )
    return parsed


def build_validation_plan(
    *,
    mission_id: str,
    executable_id: str,
    evidence_depth: str,
    planned_claims: tuple[str, ...],
    evidence_modes: tuple[str, ...],
    criteria: tuple[Mapping[str, object], ...],
    candidate_eligible_on_pass: bool = False,
) -> dict[str, object]:
    """Build a canonical-ready, noncompensatory scientific validation plan.

    Metric values are integers or null in the measurement.  Fixed-point units
    belong in metric names, for example ``selection_aware_pvalue_ppm``.
    """

    mission = _ascii("mission_id", mission_id)
    executable = _ascii("executable_id", executable_id)
    if evidence_depth not in {"discovery", "confirmation"}:
        raise EvidenceValidationError("scientific evidence depth is invalid")
    claims = _sorted_ascii_list("planned_claims", planned_claims)
    modes = _sorted_ascii_list("evidence_modes", evidence_modes)
    if type(candidate_eligible_on_pass) is not bool:
        raise EvidenceValidationError("candidate policy must be boolean")
    if evidence_depth == "discovery" and candidate_eligible_on_pass:
        raise EvidenceValidationError("discovery evidence cannot authorize a candidate")
    parsed_criteria = _criteria(criteria, claims=claims, modes=modes)
    plan: dict[str, object] = {
        "candidate_eligible_on_pass": candidate_eligible_on_pass,
        "criteria": [item.manifest() for item in parsed_criteria],
        "evidence_depth": evidence_depth,
        "evidence_modes": list(modes),
        "executable_id": executable,
        "mission_id": mission,
        "planned_claims": list(claims),
        "schema": SCIENTIFIC_VALIDATION_PLAN_SCHEMA,
    }
    canonical_bytes(plan)
    return plan


def _parse_plan(value: object) -> tuple[dict[str, Any], tuple[_Criterion, ...]]:
    if (
        not isinstance(value, dict)
        or set(value) != _PLAN_FIELDS
        or value.get("schema") != SCIENTIFIC_VALIDATION_PLAN_SCHEMA
    ):
        raise EvidenceValidationError("scientific validation plan schema is invalid")
    _ascii("plan mission_id", value["mission_id"])
    _ascii("plan executable_id", value["executable_id"])
    depth = value["evidence_depth"]
    if depth not in {"discovery", "confirmation"}:
        raise EvidenceValidationError("scientific plan depth is invalid")
    candidate_policy = value["candidate_eligible_on_pass"]
    if type(candidate_policy) is not bool:
        raise EvidenceValidationError("scientific candidate policy is invalid")
    if depth == "discovery" and candidate_policy:
        raise EvidenceValidationError("discovery plan cannot authorize a candidate")
    claims = _sorted_ascii_list("plan claims", value["planned_claims"])
    modes = _sorted_ascii_list("plan evidence modes", value["evidence_modes"])
    criteria = _criteria(value["criteria"], claims=claims, modes=modes)
    return value, criteria


def _parse_measurement(
    value: object,
    *,
    claims: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, dict[str, int | None]]]:
    if (
        not isinstance(value, dict)
        or set(value) != _MEASUREMENT_FIELDS
        or value.get("schema") != SCIENTIFIC_MEASUREMENT_SCHEMA
    ):
        raise EvidenceValidationError("scientific measurement schema is invalid")
    if _sorted_ascii_list("measurement claims", value["claims"]) != claims:
        raise EvidenceValidationError("scientific measurement claims differ from plan")
    _digest("measurement evaluation artifact", value["evaluation_artifact_hash"])
    metrics = value["metrics"]
    if not isinstance(metrics, dict) or set(metrics) != set(claims):
        raise EvidenceValidationError("scientific measurement metrics are not claim-bound")
    normalized: dict[str, dict[str, int | None]] = {}
    for claim_id in claims:
        claim_metrics = metrics[claim_id]
        if not isinstance(claim_metrics, dict) or not claim_metrics:
            raise EvidenceValidationError("scientific claim has no raw metrics")
        normalized_metrics: dict[str, int | None] = {}
        for metric_name, metric_value in claim_metrics.items():
            metric = _ascii("measurement metric", metric_name)
            if metric_value is not None and type(metric_value) is not int:
                raise EvidenceValidationError(
                    "scientific raw metrics must be integer or null"
                )
            normalized_metrics[metric] = metric_value
        normalized[claim_id] = normalized_metrics
    return value, normalized


def _trend_evaluation(
    value: object,
    *,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> dict[str, Any]:
    schema, expected_context_count, expected_total_exposures = _evaluation_profile(
        value.get("schema") if isinstance(value, dict) else None
    )
    if (
        not isinstance(value, dict)
        or set(value) != _TREND_EVALUATION_FIELDS
    ):
        raise EvidenceValidationError("trend evaluation schema is invalid")
    if value.get("subject_executable_id") != executable_id:
        raise EvidenceValidationError("trend evaluation belongs to another Executable")
    _digest("trend surface artifact", value.get("surface_artifact_hash"))
    _digest("trend surface manifest", value.get("surface_manifest_hash"))
    execution = value.get("job_execution")
    if not isinstance(execution, dict) or set(execution) != {
        "identity",
        "job_hash",
        "job_id",
        "job_permit_id",
        "start_record_id",
    }:
        raise EvidenceValidationError("trend Job execution binding is invalid")
    for name in ("identity", "job_hash", "job_permit_id", "start_record_id"):
        _digest(f"trend Job execution {name}", execution.get(name))
    if (
        execution.get("job_id") != job_id
        or execution.get("job_hash") != job_hash
        or execution.get("identity")
        != canonical_digest(
            domain="running-job-execution",
            payload={
                name: execution[name]
                for name in (
                    "job_hash",
                    "job_id",
                    "job_permit_id",
                    "start_record_id",
                )
            },
        )
    ):
        raise EvidenceValidationError("trend Job execution identity differs")
    _ascii("trend subject configuration", value.get("subject_configuration_id"))
    metrics = value.get("metrics")
    if (
        not isinstance(metrics, dict)
        or not metrics
        or any(type(name) is not str or type(metric) is not int for name, metric in metrics.items())
    ):
        raise EvidenceValidationError("trend evaluation metrics are invalid")
    evaluable = value.get("evaluable")
    if type(evaluable) is not bool:
        raise EvidenceValidationError("trend evaluation evaluability is invalid")
    expected_evaluable = all(
        metrics.get(name) == 0
        for name in (
            "append_invariance_mismatch_count",
            "causality_violation_count",
            "nonfinite_metric_count",
            "prefix_invariance_mismatch_count",
            "unknown_cost_unresolved_signal_count",
        )
    )
    if evaluable != expected_evaluable:
        raise EvidenceValidationError("trend evaluability differs from raw invariants")
    folds = value.get("fold_metrics")
    if not isinstance(folds, list) or len(folds) != 9:
        raise EvidenceValidationError("trend evaluation must contain nine folds")
    if [item.get("fold_id") for item in folds if isinstance(item, dict)] != [
        f"rw_{index:03d}" for index in range(1, 10)
    ]:
        raise EvidenceValidationError("trend fold identities are invalid")
    for item in folds:
        if (
            not isinstance(item, dict)
            or any(type(child) not in {str, int} for child in item.values())
        ):
            raise EvidenceValidationError("trend fold metrics are invalid")
    expected_lengths = {
        "regime_metrics": 3,
        "session_metrics": 4,
        "direction_metrics": 2,
    }
    for name, expected_length in expected_lengths.items():
        items = value.get(name)
        if not isinstance(items, list) or len(items) != expected_length:
            raise EvidenceValidationError(f"trend {name} are invalid")
        if any(
            not isinstance(item, dict)
            or any(type(child) not in {str, int} for child in item.values())
            for item in items
        ):
            raise EvidenceValidationError(f"trend {name} values are invalid")
    context = value.get("selection_context")
    if not isinstance(context, list) or len(context) != expected_context_count:
        raise EvidenceValidationError("scientific selection context count is invalid")
    identities: set[str] = set()
    subject_rows = 0
    for item in context:
        if not isinstance(item, dict) or set(item) != {
            "configuration_id",
            "executable_id",
            "net_profit_micropoints",
            "selection_aware_pvalue_ppm",
        }:
            raise EvidenceValidationError("trend selection row schema is invalid")
        _ascii("trend configuration_id", item["configuration_id"])
        identity = _ascii("trend executable_id", item["executable_id"])
        if not identity.startswith("executable:") or len(identity) != 75:
            raise EvidenceValidationError("trend selection executable identity is invalid")
        if identity in identities:
            raise EvidenceValidationError("trend selection Executables are duplicated")
        identities.add(identity)
        if type(item["net_profit_micropoints"]) is not int or type(
            item["selection_aware_pvalue_ppm"]
        ) is not int:
            raise EvidenceValidationError("trend selection metrics are invalid")
        if identity == executable_id:
            subject_rows += 1
            if (
                item["net_profit_micropoints"]
                != metrics.get("net_profit_micropoints")
                or item["selection_aware_pvalue_ppm"]
                != metrics.get("selection_aware_pvalue_ppm")
            ):
                raise EvidenceValidationError("trend subject selection metrics differ")
    if subject_rows != 1:
        raise EvidenceValidationError("trend subject is absent from selection context")
    selection_method = value.get("selection_method")
    if selection_method != {
        "bootstrap_samples": 41999,
        "block_days": [5, 10, 20],
        "method": (
            "centered_non_circular_moving_block_studentized_one_sided_"
            "then_bonferroni"
        ),
        "monte_carlo_upper_confidence_ppm": 990000,
        "multiple_block_rule": "maximum_adjusted_pvalue",
        "paired_control_rule": (
            "same_eligible_decision_day_intersection_union_worst_control"
        ),
        "seed": 612337279,
        "seed_derivation": "sha256_base_seed_label_block_length_first_u64",
        "total_exposures": expected_total_exposures,
    }:
        raise EvidenceValidationError("trend selection method differs from preregistration")
    if value.get("session_semantics") != (
        "broker_clock_fixed_bins_no_dst_or_cash_session_claim"
    ):
        raise EvidenceValidationError("trend session semantics are invalid")
    limits = value.get("claim_limits")
    if not isinstance(limits, list) or any(type(item) is not str for item in limits):
        raise EvidenceValidationError("trend claim limits are invalid")
    return value


def _criterion_passed(criterion: _Criterion, value: int) -> bool:
    return {
        "eq": value == criterion.threshold,
        "ge": value >= criterion.threshold,
        "gt": value > criterion.threshold,
        "le": value <= criterion.threshold,
        "lt": value < criterion.threshold,
    }[criterion.operator]


def _verdict(
    criteria: tuple[_Criterion, ...], metrics: Mapping[str, Mapping[str, int | None]]
) -> str:
    unavailable = False
    failed = False
    for criterion in criteria:
        claim_metrics = metrics[criterion.claim_id]
        if criterion.metric not in claim_metrics:
            raise EvidenceValidationError(
                "scientific measurement omits a preregistered raw metric"
            )
        value = claim_metrics[criterion.metric]
        if value is None:
            unavailable = True
        elif not _criterion_passed(criterion, value):
            failed = True
    if unavailable:
        return "not_evaluable"
    if failed:
        return "failed"
    return "passed"


_THIS_IMPLEMENTATION = Path(__file__).resolve()
SCIENTIFIC_DISCOVERY_VALIDATOR_ID = validator_identity(
    protocol=SCIENTIFIC_VALIDATION_PROTOCOL,
    domains=SCIENTIFIC_VALIDATION_DOMAINS,
    implementation_sha256=sha256(_THIS_IMPLEMENTATION.read_bytes()).hexdigest(),
)


class ScientificDiscoveryValidator:
    """Validate discovery or explicit confirmation from raw integer metrics."""

    validator_id = SCIENTIFIC_DISCOVERY_VALIDATOR_ID
    domains = SCIENTIFIC_VALIDATION_DOMAINS
    implementation_path = _THIS_IMPLEMENTATION
    protocol = SCIENTIFIC_VALIDATION_PROTOCOL

    def preflight_binding(
        self, *, domain: str, binding: Mapping[str, Any]
    ) -> None:
        value = _plain(binding)
        if (
            domain != "scientific"
            or not isinstance(value, dict)
            or value.get("validator_id") != self.validator_id
        ):
            raise EvidenceValidationError(
                "scientific validator preflight binding is invalid"
            )
        if set(value) == _SCIENTIFIC_BINDING_FIELDS:
            raise EvidenceValidationError(
                "scientific evaluation schema must be declared before Job execution"
            )
        if set(value) != _SCIENTIFIC_PREFLIGHT_BINDING_FIELDS:
            raise EvidenceValidationError(
                "scientific validator preflight binding is invalid"
            )
        require_supported_evaluation_schema(value["evaluation_schema"])

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if (
            request.domain != "scientific"
            or request.engineering_fixture
            or request.validator_id != self.validator_id
        ):
            raise EvidenceValidationError("scientific validator request is unauthorized")

        captured = tuple(
            (artifact, artifact.read_bytes()) for artifact in request.artifacts
        )
        for artifact, _ in captured:
            artifact.require_source_unchanged()

        parsed: list[tuple[Any, dict[str, Any]]] = []
        for artifact, content in captured:
            try:
                value = parse_canonical(content)
            except (TypeError, ValueError) as exc:
                raise EvidenceValidationError(
                    "scientific durable artifact is not canonical"
                ) from exc
            if not isinstance(value, dict):
                raise EvidenceValidationError(
                    "scientific durable artifact must be a canonical object"
                )
            _ascii("durable artifact schema", value.get("schema"))
            parsed.append((artifact, value))

        def artifacts_with_schema(schema: str) -> list[tuple[Any, dict[str, Any]]]:
            return [item for item in parsed if item[1].get("schema") == schema]

        plan_items = artifacts_with_schema(SCIENTIFIC_VALIDATION_PLAN_SCHEMA)
        measurement_items = artifacts_with_schema(SCIENTIFIC_MEASUREMENT_SCHEMA)
        result_items = artifacts_with_schema(SCIENTIFIC_RESULT_SCHEMA)
        if len(plan_items) != 1 or len(measurement_items) != 1 or len(result_items) != 1:
            raise EvidenceValidationError(
                "scientific outputs require one plan, measurement, and result manifest"
            )
        plan_artifact, plan_value = plan_items[0]
        measurement_artifact, measurement_value = measurement_items[0]
        result_artifact, result_value = result_items[0]

        if plan_artifact.sha256 != request.validation_plan_hash:
            raise EvidenceValidationError("scientific plan hash differs from request")
        binding = _plain(request.binding)
        if (
            not isinstance(binding, dict)
            or frozenset(binding)
            not in {
                frozenset(_SCIENTIFIC_BINDING_FIELDS),
                frozenset(_SCIENTIFIC_PREFLIGHT_BINDING_FIELDS),
            }
        ):
            raise EvidenceValidationError("scientific validator binding schema is invalid")
        if (
            binding["validator_id"] != self.validator_id
            or binding["validation_plan_hash"] != request.validation_plan_hash
            or result_artifact.output_name != binding["result_manifest_output"]
        ):
            raise EvidenceValidationError("scientific validator binding is inconsistent")
        if _plain(request.result_manifest) != result_value:
            raise EvidenceValidationError("caller result manifest differs from artifact")
        subject = _plain(request.evidence_subject)
        if (
            not isinstance(subject, dict)
            or set(subject) != {"id", "kind"}
            or subject["kind"] != "Executable"
        ):
            raise EvidenceValidationError("scientific evidence subject is invalid")
        executable_id = _ascii("evidence executable_id", subject["id"])

        plan, criteria = _parse_plan(plan_value)
        claims = _sorted_ascii_list("binding planned claims", binding["planned_claims"])
        modes = _sorted_ascii_list("binding evidence modes", binding["evidence_modes"])
        if (
            plan["mission_id"] != request.mission_id
            or plan["executable_id"] != executable_id
            or plan["evidence_depth"] != binding["evidence_depth"]
            or tuple(plan["planned_claims"]) != claims
            or tuple(plan["evidence_modes"]) != modes
        ):
            raise EvidenceValidationError("scientific plan differs from Job binding")

        measurement, metrics = _parse_measurement(measurement_value, claims=claims)
        evaluation_hash = measurement["evaluation_artifact_hash"]
        evaluation_items = [
            (artifact, value)
            for artifact, value in parsed
            if artifact.sha256 == evaluation_hash
        ]
        if len(evaluation_items) != 1:
            raise EvidenceValidationError(
                "scientific measurement lacks its exact evaluation artifact"
            )
        evaluation_artifact, evaluation_value = evaluation_items[0]
        if any(
            evaluation_artifact is item
            for item in (plan_artifact, measurement_artifact, result_artifact)
        ):
            raise EvidenceValidationError("scientific evaluation artifact role is invalid")
        declared_evaluation_schema = binding.get("evaluation_schema")
        if declared_evaluation_schema is not None and (
            require_supported_evaluation_schema(declared_evaluation_schema)
            != evaluation_value.get("schema")
        ):
            raise EvidenceValidationError(
                "scientific evaluation schema differs from Job binding"
            )
        evaluation = _trend_evaluation(
            evaluation_value,
            executable_id=executable_id,
            job_hash=measurement["job_hash"],
            job_id=measurement["job_id"],
        )
        raw_evaluation_metrics = evaluation["metrics"]
        for claim_metrics in metrics.values():
            for metric_name, metric_value in claim_metrics.items():
                if metric_name not in raw_evaluation_metrics:
                    raise EvidenceValidationError(
                        "scientific measurement metric is absent from evaluation"
                    )
                if metric_value is None:
                    if evaluation["evaluable"] is True:
                        raise EvidenceValidationError(
                            "evaluable trend evidence contains a null measurement"
                        )
                elif metric_value != raw_evaluation_metrics[metric_name]:
                    raise EvidenceValidationError(
                        "scientific measurement differs from raw evaluation"
                    )
        if (
            measurement["mission_id"] != request.mission_id
            or measurement["job_id"] != request.job_id
            or measurement["job_hash"] != request.job_hash
            or measurement["executable_id"] != executable_id
            or measurement["evidence_depth"] != binding["evidence_depth"]
            or tuple(measurement["evidence_modes"]) != modes
        ):
            raise EvidenceValidationError(
                "scientific measurement belongs to another execution"
            )

        if not isinstance(result_value, dict) or set(result_value) != _RESULT_FIELDS:
            raise EvidenceValidationError("scientific result manifest schema is invalid")
        if (
            result_value["mission_id"] != request.mission_id
            or result_value["job_id"] != request.job_id
            or result_value["job_hash"] != request.job_hash
            or result_value["executable_id"] != executable_id
            or result_value["evidence_depth"] != binding["evidence_depth"]
        ):
            raise EvidenceValidationError(
                "scientific result manifest belongs to another execution"
            )
        observations = result_value["observations"]
        if not isinstance(observations, list) or len(observations) != len(claims):
            raise EvidenceValidationError("scientific observations are invalid")
        observed_claims: list[str] = []
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) != {
                "claim_id",
                "measurement_artifact_hash",
            }:
                raise EvidenceValidationError("scientific observation schema is invalid")
            observed_claims.append(_ascii("observation claim_id", observation["claim_id"]))
            if observation["measurement_artifact_hash"] != measurement_artifact.sha256:
                raise EvidenceValidationError(
                    "scientific observation is not bound to the measurement"
                )
        if tuple(observed_claims) != claims:
            raise EvidenceValidationError(
                "scientific result claims differ from preregistration"
            )

        verdict = _verdict(criteria, metrics)
        candidate_eligible = bool(
            verdict == "passed"
            and binding["evidence_depth"] == "confirmation"
            and plan["candidate_eligible_on_pass"] is True
        )
        for artifact, _ in captured:
            artifact.require_source_unchanged()
        return ValidatedEvidence(
            verdict=verdict,
            claims=claims,
            measurement_artifact_hashes=(measurement_artifact.sha256,),
            facts={"executed_evidence_modes": list(modes)},
            scientific_eligible=True,
            candidate_eligible=candidate_eligible,
            release_eligible=False,
        )


__all__ = [
    "SCIENTIFIC_CRITERION_OPERATORS",
    "SCIENTIFIC_DISCOVERY_VALIDATOR_ID",
    "SCIENTIFIC_MEASUREMENT_SCHEMA",
    "SCIENTIFIC_RESULT_SCHEMA",
    "SCIENTIFIC_VALIDATION_DOMAINS",
    "SCIENTIFIC_VALIDATION_PLAN_SCHEMA",
    "SCIENTIFIC_VALIDATION_PROTOCOL",
    "ScientificDiscoveryValidator",
    "build_validation_plan",
    "require_supported_evaluation_schema",
]
