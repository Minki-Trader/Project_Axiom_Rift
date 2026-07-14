"""P0 audit-integrity support and deterministic statistical proof validation.

This module owns the selected-set audit's concrete schemas and recalculation.
The generic evidence-proof router deliberately knows only that audit integrity
requires one support artifact and one statistical artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import selection_inference as selection_module


AUDIT_INTEGRITY_MODE = "audit_integrity"
P0_FOREST_SUPPORT_SCHEMA = "p0_forest_composite_support.v3"
SELECTION_STATISTICAL_SCHEMA = "selection_inference_statistical.v2"
AUDIT_SUPPORT_PROOF_KIND = "audit_support_manifest.v1"
AUDIT_STATISTICAL_PROOF_KIND = "audit_statistical_manifest.v1"

_VALIDITY_METRICS = frozenset(
    {
        "append_invariance_mismatch_count",
        "causality_violation_count",
        "nonfinite_metric_count",
        "prefix_invariance_mismatch_count",
        "unknown_cost_unresolved_signal_count",
    }
)
_SUPPORT_FIELDS = {
    "analysis_plan",
    "authority",
    "baseline_executable_id",
    "calendar",
    "candidate_authority",
    "claim_limits",
    "common_parent_artifacts",
    "composite_executable_id",
    "dataset_sha256",
    "economic_composite",
    "family_inventory_hash",
    "historical_search_context",
    "implementation",
    "inventory_artifact_sha256",
    "job_hash",
    "job_id",
    "members",
    "mission_id",
    "pnl_attribution",
    "post_selection_diagnostics",
    "replayed_set_id",
    "schema",
    "split_artifact_sha256",
    "statistical_plan",
}
_MEMBER_FIELDS = {
    "adapter",
    "axis_replay_sha256",
    "configuration_id",
    "descriptive_metrics",
    "legacy_evaluation_sha256",
    "legacy_executable_id",
    "legacy_study_id",
    "ordinal",
}
_STATISTICAL_FIELDS = {
    "engine_environment",
    "hypotheses",
    "implementation_sha256",
    "input_binding",
    "method",
    "plan",
    "schema",
    "seeds",
}


class AuditIntegrityProofError(ValueError):
    """The P0 audit proof pair is absent, forged, or inconsistent."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise AuditIntegrityProofError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise AuditIntegrityProofError(f"{name} must be a SHA-256 digest")
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    head, separator, digest = text.partition(":")
    if not separator or head != prefix:
        raise AuditIntegrityProofError(f"{name} has the wrong identity domain")
    _digest(f"{name} digest", digest)
    return text


def _mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditIntegrityProofError(f"{name} must be a mapping")
    return value


def _sequence(name: str, value: object) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)) or not value:
        raise AuditIntegrityProofError(f"{name} must be a non-empty sequence")
    return value


def _positive_int(name: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise AuditIntegrityProofError(f"{name} must be a positive integer")
    return value


def _ppm(name: str, value: object) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise AuditIntegrityProofError(f"{name} must be an integer p-value")
    return value


def _typed_plan(raw_plan: Mapping[str, Any]) -> Any:
    expected = {
        "alpha_ppm",
        "base_seed",
        "block_lengths",
        "bootstrap_samples",
        "candidate_authority",
        "family_id",
        "family_size",
        "hypotheses",
        "monte_carlo_confidence_ppm",
        "schema",
        "stage",
    }
    if set(raw_plan) != expected:
        raise AuditIntegrityProofError("statistical plan schema is invalid")
    try:
        hypotheses = tuple(
            selection_module.SelectionHypothesis(
                hypothesis_id=_ascii(
                    "registered hypothesis_id",
                    _mapping("registered hypothesis", item).get("hypothesis_id"),
                ),
                registration_id=_ascii(
                    "registered registration_id",
                    _mapping("registered hypothesis", item).get("registration_id"),
                ),
            )
            for item in _sequence("registered hypotheses", raw_plan["hypotheses"])
        )
        plan = selection_module.SelectionFamilyPlan(
            family_id=_ascii("statistical family_id", raw_plan["family_id"]),
            stage=_ascii("statistical stage", raw_plan["stage"]),
            hypotheses=hypotheses,
            alpha_ppm=raw_plan["alpha_ppm"],
            bootstrap_samples=raw_plan["bootstrap_samples"],
            block_lengths=tuple(raw_plan["block_lengths"]),
            monte_carlo_confidence_ppm=raw_plan[
                "monte_carlo_confidence_ppm"
            ],
            base_seed=raw_plan["base_seed"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuditIntegrityProofError("statistical plan is invalid") from exc
    if plan.manifest() != dict(raw_plan):
        raise AuditIntegrityProofError(
            "statistical plan differs from typed preregistration"
        )
    return plan


def _tail(raw: Mapping[str, Any], *, plan: Any, label: str) -> tuple[int, int]:
    if set(raw) != {
        "exceedance_count",
        "monte_carlo_upper_pvalue_ppm",
        "point_pvalue_ppm",
    }:
        raise AuditIntegrityProofError(f"{label} tail schema is invalid")
    count = raw["exceedance_count"]
    if type(count) is not int or not 0 <= count <= plan.bootstrap_samples:
        raise AuditIntegrityProofError(f"{label} exceedance count is invalid")
    expected = selection_module._tail_values(exceedances=count, plan=plan)
    if (
        raw["point_pvalue_ppm"] != expected[0]
        or raw["monte_carlo_upper_pvalue_ppm"] != expected[1]
    ):
        raise AuditIntegrityProofError(
            f"{label} p-values do not recompute from exceedance counts"
        )
    return expected


def validate_statistical_manifest(statistical: Mapping[str, Any]) -> dict[str, Any]:
    """Recalculate the compact statistical manifest from durable counts."""

    if (
        set(statistical) != _STATISTICAL_FIELDS
        or statistical.get("schema") != SELECTION_STATISTICAL_SCHEMA
    ):
        raise AuditIntegrityProofError("audit statistical artifact schema is invalid")
    if _digest(
        "statistical implementation", statistical["implementation_sha256"]
    ) != selection_module.selection_inference_implementation_sha256():
        raise AuditIntegrityProofError(
            "statistical artifact is not bound to current implementation"
        )
    plan = _typed_plan(_mapping("statistical plan", statistical["plan"]))
    expected_seeds = tuple(
        selection_module._bootstrap_seed(
            plan=plan,
            block_length=block_length,
        ).manifest()
        for block_length in plan.block_lengths
    )
    seeds = tuple(_sequence("statistical seeds", statistical["seeds"]))
    if seeds != expected_seeds:
        raise AuditIntegrityProofError(
            "statistical seeds differ from deterministic block plan"
        )
    input_binding = _mapping("statistical input binding", statistical["input_binding"])
    if set(input_binding) != {
        "calendar_identity",
        "daily_pnl_identity",
        "date_count",
        "first_date",
        "last_date",
        "missing_day_policy",
    }:
        raise AuditIntegrityProofError("statistical input binding schema is invalid")
    date_count = _positive_int("statistical date_count", input_binding["date_count"])
    calendar_identity = _identity(
        "statistical calendar", input_binding["calendar_identity"], "calendar"
    )
    daily_pnl_identity = _identity(
        "statistical daily PnL", input_binding["daily_pnl_identity"], "daily-pnl"
    )
    if (
        input_binding["missing_day_policy"]
        != "exact_shared_calendar_no_implicit_zero_fill"
        or any(length >= date_count for length in plan.block_lengths)
    ):
        raise AuditIntegrityProofError("statistical calendar policy is invalid")
    _ascii("statistical first_date", input_binding["first_date"])
    _ascii("statistical last_date", input_binding["last_date"])
    expected_environment = {
        "numpy": selection_module.np.__version__,
        "python": ".".join(
            str(value) for value in selection_module.sys.version_info[:3]
        ),
        "scipy": selection_module.scipy.__version__,
    }
    if dict(_mapping("statistical environment", statistical["engine_environment"])) != expected_environment:
        raise AuditIntegrityProofError("statistical environment drifted")
    expected_method = {
        "block_aggregation": selection_module.SELECTION_BLOCK_AGGREGATION,
        "bootstrap": selection_module.SELECTION_BOOTSTRAP_METHOD,
        "familywise": [
            selection_module.SELECTION_BONFERRONI_METHOD,
            selection_module.SELECTION_MAX_STATISTIC_METHOD,
            selection_module.SELECTION_ROMANO_WOLF_METHOD,
        ],
        "historical_exposure_adjustment": "forbidden",
        "monte_carlo_upper": selection_module.SELECTION_MONTE_CARLO_UPPER_METHOD,
        "raw_point": selection_module.SELECTION_RAW_POINT_METHOD,
        "references": list(selection_module._METHOD_REFERENCES),
        "resampling_familywise_scope": (
            "approximate_dependence_aware_fwer_not_finite_sample_guarantee"
        ),
    }
    if dict(_mapping("statistical method", statistical["method"])) != expected_method:
        raise AuditIntegrityProofError("statistical method drifted")
    hypotheses = _sequence("statistical hypotheses", statistical["hypotheses"])
    if len(hypotheses) != plan.family_size:
        raise AuditIntegrityProofError("statistical family size drifted")
    observed_ids: list[str] = []
    raw_values: list[tuple[int, int]] = []
    per_block_ranked: dict[int, list[tuple[int | None, bool, tuple[int, int], tuple[int, int]]]] = {
        block_length: [] for block_length in plan.block_lengths
    }
    for raw_hypothesis in hypotheses:
        hypothesis = _mapping("statistical hypothesis", raw_hypothesis)
        if set(hypothesis) != {
            "block_results",
            "evaluable",
            "family_id",
            "family_size",
            "familywise",
            "hypothesis_id",
            "observed",
            "raw",
            "validator_v2_multiplicity",
        }:
            raise AuditIntegrityProofError("statistical hypothesis schema is invalid")
        hypothesis_id = _ascii("hypothesis_id", hypothesis["hypothesis_id"])
        observed_ids.append(hypothesis_id)
        evaluable = hypothesis["evaluable"]
        if (
            type(evaluable) is not bool
            or hypothesis["family_id"] != plan.family_id
            or hypothesis["family_size"] != plan.family_size
        ):
            raise AuditIntegrityProofError("statistical hypothesis binding drifted")
        observed = _mapping("statistical observed", hypothesis["observed"])
        if (
            set(observed)
            != {
                "mean_denominator_days",
                "studentized_statistic_ppb",
                "studentized_statistic_scale",
                "sum_micropoints",
            }
            or observed["mean_denominator_days"] != date_count
            or observed["studentized_statistic_scale"]
            != selection_module.SELECTION_STATISTIC_SCALE
            or type(observed["studentized_statistic_ppb"]) is not int
            or type(observed["sum_micropoints"]) is not int
        ):
            raise AuditIntegrityProofError("statistical observed values are invalid")
        block_results = _sequence("block results", hypothesis["block_results"])
        if len(block_results) != len(plan.block_lengths):
            raise AuditIntegrityProofError("block results differ from plan")
        raw_tails: list[tuple[int, int]] = []
        max_tails: list[tuple[int, int]] = []
        stepdown_tails: list[tuple[int, int]] = []
        for block_length, raw_block in zip(
            plan.block_lengths, block_results, strict=True
        ):
            block = _mapping("block result", raw_block)
            if (
                set(block)
                != {
                    "block_length",
                    "hypothesis_id",
                    "raw",
                    "romano_wolf",
                    "synchronized_max",
                }
                or block["block_length"] != block_length
                or block["hypothesis_id"] != hypothesis_id
            ):
                raise AuditIntegrityProofError("block result identity is invalid")
            raw_tail = _tail(
                _mapping("block raw", block["raw"]), plan=plan, label="block"
            )
            max_tail = _tail(
                _mapping("block max", block["synchronized_max"]),
                plan=plan,
                label="synchronized max",
            )
            romano = _mapping("Romano-Wolf block", block["romano_wolf"])
            if set(romano) != {
                "intersection_exceedance_count",
                "intersection_monte_carlo_upper_pvalue_ppm",
                "intersection_point_pvalue_ppm",
                "rank",
                "stepdown_monte_carlo_upper_pvalue_ppm",
                "stepdown_point_pvalue_ppm",
            }:
                raise AuditIntegrityProofError("Romano-Wolf schema is invalid")
            intersection = _tail(
                {
                    "exceedance_count": romano["intersection_exceedance_count"],
                    "monte_carlo_upper_pvalue_ppm": romano[
                        "intersection_monte_carlo_upper_pvalue_ppm"
                    ],
                    "point_pvalue_ppm": romano["intersection_point_pvalue_ppm"],
                },
                plan=plan,
                label="Romano-Wolf",
            )
            rank = romano["rank"]
            if rank is not None and (
                type(rank) is not int or not 1 <= rank <= plan.family_size
            ):
                raise AuditIntegrityProofError("Romano-Wolf rank is invalid")
            stepdown = (
                _ppm("stepdown point", romano["stepdown_point_pvalue_ppm"]),
                _ppm(
                    "stepdown upper",
                    romano["stepdown_monte_carlo_upper_pvalue_ppm"],
                ),
            )
            if not evaluable and (rank is not None or stepdown != (1_000_000, 1_000_000)):
                raise AuditIntegrityProofError(
                    "non-evaluable Romano-Wolf result is not conservative"
                )
            raw_tails.append(raw_tail)
            max_tails.append(max_tail)
            stepdown_tails.append(stepdown)
            per_block_ranked[block_length].append(
                (rank, evaluable, intersection, stepdown)
            )
        worst_raw = (
            max(item[0] for item in raw_tails),
            max(item[1] for item in raw_tails),
        )
        if dict(_mapping("hypothesis raw", hypothesis["raw"])) != {
            "monte_carlo_upper_pvalue_ppm": worst_raw[1],
            "point_pvalue_ppm": worst_raw[0],
        }:
            raise AuditIntegrityProofError("worst-block raw p-values do not recompute")
        raw_values.append(worst_raw)
        expected_familywise = {
            "bonferroni": (
                min(1_000_000, worst_raw[0] * plan.family_size),
                min(1_000_000, worst_raw[1] * plan.family_size),
            ),
            "romano_wolf_stepdown": (
                max(item[0] for item in stepdown_tails),
                max(item[1] for item in stepdown_tails),
            ),
            "synchronized_max": (
                max(item[0] for item in max_tails),
                max(item[1] for item in max_tails),
            ),
        }
        familywise = _mapping("hypothesis familywise", hypothesis["familywise"])
        if set(familywise) != set(expected_familywise):
            raise AuditIntegrityProofError("familywise schema is invalid")
        for method, tail in expected_familywise.items():
            if dict(_mapping(f"familywise {method}", familywise[method])) != {
                "monte_carlo_upper_pvalue_ppm": tail[1],
                "point_pvalue_ppm": tail[0],
                "reject_at_alpha": bool(evaluable and tail[1] <= plan.alpha_ppm),
            }:
                raise AuditIntegrityProofError("familywise values do not recompute")
        expected_multiplicity = selection_module.bonferroni_concurrent_family(
            criterion_id="E01-familywise-selection",
            family_id=plan.family_id,
            family_size=plan.family_size,
            raw_pvalue_ppm=worst_raw[1],
            alpha_ppm=plan.alpha_ppm,
        ).manifest()
        if dict(_mapping("validator multiplicity", hypothesis["validator_v2_multiplicity"])) != expected_multiplicity:
            raise AuditIntegrityProofError("validator multiplicity does not recompute")
    if tuple(observed_ids) != plan.hypothesis_ids:
        raise AuditIntegrityProofError("statistical hypotheses differ from registration")
    for records in per_block_ranked.values():
        active = sorted((item for item in records if item[1]), key=lambda item: int(item[0]))
        if tuple(item[0] for item in active) != tuple(range(1, len(active) + 1)):
            raise AuditIntegrityProofError("Romano-Wolf ranks are incomplete")
        prior = (0, 0)
        for _, _, intersection, stepdown in active:
            prior = (max(prior[0], intersection[0]), max(prior[1], intersection[1]))
            if stepdown != prior:
                raise AuditIntegrityProofError("Romano-Wolf stepdown does not recompute")
    return {
        "alpha_ppm": plan.alpha_ppm,
        "block_lengths": plan.block_lengths,
        "bootstrap_samples": plan.bootstrap_samples,
        "calendar_identity": calendar_identity,
        "daily_pnl_identity": daily_pnl_identity,
        "date_count": date_count,
        "hypothesis_ids": tuple(observed_ids),
        "raw_values": tuple(raw_values),
        "seed_count": len(seeds),
        "statistical_identity": (
            "selection-statistical:"
            + canonical_digest(
                domain="selection-inference-statistical",
                payload=dict(statistical),
            )
        ),
    }


def validate_p0_audit_pair(
    *,
    support: Mapping[str, Any],
    support_hash: str,
    statistical: Mapping[str, Any],
    statistical_hash: str,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> dict[str, int]:
    """Validate the exact support/statistical pair and derive audit metrics."""

    if set(support) != _SUPPORT_FIELDS or support.get("schema") != P0_FOREST_SUPPORT_SCHEMA:
        raise AuditIntegrityProofError("audit support artifact schema is invalid")
    _digest("audit support hash", support_hash)
    _digest("audit statistical hash", statistical_hash)
    if (
        support.get("authority") != "post_selection_descriptive_audit_only"
        or support.get("candidate_authority") != "none"
        or support.get("economic_composite") is not False
        or support.get("mission_id") != mission_id
        or support.get("composite_executable_id") != executable_id
        or support.get("job_id") != job_id
        or support.get("job_hash") != job_hash
    ):
        raise AuditIntegrityProofError("audit authority or execution binding is invalid")
    baseline = _identity(
        "audit baseline", support.get("baseline_executable_id"), "executable"
    )
    if baseline == executable_id:
        raise AuditIntegrityProofError("audit baseline equals subject")
    if _mapping("audit analysis plan", support["analysis_plan"]).get("economic_composite") is not False:
        raise AuditIntegrityProofError("audit plan impersonates economic composite")
    if dict(_mapping("audit attribution", support["pnl_attribution"])) != {
        "daily_pnl": "decision_day",
        "monthly_drawdown": "exit_day",
        "timezone_basis": "source_timestamp_observed_coordinate",
    }:
        raise AuditIntegrityProofError("audit PnL attribution is not exact")
    facts = validate_statistical_manifest(statistical)
    input_binding = _mapping("statistical input", statistical["input_binding"])
    if dict(_mapping("audit calendar", support["calendar"])) != {
        "calendar_identity": facts["calendar_identity"],
        "daily_pnl_identity": facts["daily_pnl_identity"],
        "date_count": facts["date_count"],
        "first_date": input_binding["first_date"],
        "last_date": input_binding["last_date"],
        "missing_day_policy": "exact_shared_calendar_no_implicit_zero_fill",
    }:
        raise AuditIntegrityProofError("audit calendar differs from statistics")
    parents = _mapping("audit parents", support["common_parent_artifacts"])
    if set(parents) != {"daily_pnl", "inference", "statistical_inference"}:
        raise AuditIntegrityProofError("audit parent inventory is incomplete")
    statistical_parent = _mapping("audit statistical parent", parents["statistical_inference"])
    if (
        statistical_parent.get("sha256") != statistical_hash
        or statistical_parent.get("statistical_identity")
        != facts["statistical_identity"]
    ):
        raise AuditIntegrityProofError("audit statistical parent is forged")
    for parent in parents.values():
        value = _mapping("audit parent", parent)
        _ascii("audit parent output", value.get("output_path"))
        _digest("audit parent hash", value.get("sha256"))
    members = _sequence("audit members", support["members"])
    if len(members) != len(facts["hypothesis_ids"]):
        raise AuditIntegrityProofError("audit members differ from statistics")
    member_ids: list[str] = []
    validity = {name: 0 for name in _VALIDITY_METRICS}
    for ordinal, raw_member in enumerate(members, start=1):
        member = _mapping("audit member", raw_member)
        if set(member) != _MEMBER_FIELDS or member.get("ordinal") != ordinal:
            raise AuditIntegrityProofError("audit member schema is invalid")
        member_ids.append(
            _identity(
                "audit member executable",
                member["legacy_executable_id"],
                "executable",
            )
        )
        _digest("axis replay hash", member["axis_replay_sha256"])
        _digest("legacy evaluation hash", member["legacy_evaluation_sha256"])
        metrics = _mapping("audit descriptive metrics", member["descriptive_metrics"])
        if not _VALIDITY_METRICS.issubset(metrics):
            raise AuditIntegrityProofError("audit member omits validity metrics")
        for name, value in metrics.items():
            _ascii("audit metric", name)
            if value is not None and type(value) is not int:
                raise AuditIntegrityProofError("audit metric must be integer or null")
        for name in _VALIDITY_METRICS:
            if type(metrics[name]) is not int:
                raise AuditIntegrityProofError("audit validity metric must be integer")
            validity[name] += metrics[name]
    if tuple(member_ids) != facts["hypothesis_ids"]:
        raise AuditIntegrityProofError("audit member order differs from statistics")
    diagnostics = _sequence("audit diagnostics", support["post_selection_diagnostics"])
    if len(diagnostics) != len(members):
        raise AuditIntegrityProofError("audit diagnostics are incomplete")
    for ordinal, (raw, member_id, tail) in enumerate(
        zip(diagnostics, member_ids, facts["raw_values"], strict=True), start=1
    ):
        diagnostic = _mapping("audit diagnostic", raw)
        values = _mapping("audit diagnostic raw", diagnostic.get("raw"))
        if (
            diagnostic.get("ordinal") != ordinal
            or diagnostic.get("legacy_executable_id") != member_id
            or values.get("point_pvalue_ppm") != tail[0]
            or values.get("monte_carlo_upper_pvalue_ppm") != tail[1]
        ):
            raise AuditIntegrityProofError("audit diagnostic differs from statistics")
    statistical_plan = _mapping("audit statistical plan", support["statistical_plan"])
    if (
        statistical_plan.get("bootstrap_samples") != facts["bootstrap_samples"]
        or tuple(statistical_plan.get("block_lengths", ())) != facts["block_lengths"]
        or tuple(statistical_plan.get("ordered_member_ids", ())) != tuple(member_ids)
        or len(statistical_plan.get("seeds", ())) != facts["seed_count"]
    ):
        raise AuditIntegrityProofError("audit statistical plan drifted")
    _mapping("audit historical context", support["historical_search_context"])
    _digest("audit inventory artifact", support["inventory_artifact_sha256"])
    return {
        **validity,
        "bootstrap_seed_record_count": facts["seed_count"],
        "calendar_date_count": facts["date_count"],
        "candidate_authority_count": 0,
        "common_parent_artifact_count": len(parents),
        "decision_day_attribution_count": 1,
        "durable_proof_artifact_count": 2,
        "economic_composite_count": 0,
        "family_inventory_member_count": len(members),
        "historical_context_record_count": 1,
        "raw_monte_carlo_upper_record_count": len(facts["raw_values"]),
        "raw_point_pvalue_record_count": len(facts["raw_values"]),
        "replayed_member_count": len(members),
    }


__all__ = [
    "AUDIT_INTEGRITY_MODE",
    "AUDIT_STATISTICAL_PROOF_KIND",
    "AUDIT_SUPPORT_PROOF_KIND",
    "AuditIntegrityProofError",
    "P0_FOREST_SUPPORT_SCHEMA",
    "SELECTION_STATISTICAL_SCHEMA",
    "validate_p0_audit_pair",
    "validate_statistical_manifest",
]
