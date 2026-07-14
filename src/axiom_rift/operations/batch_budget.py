"""Pure manifests for additive Batch budget-reservation repair."""

from __future__ import annotations

from collections.abc import Mapping


BATCH_BUDGET_RESERVATION_REPAIR_SCHEMA = (
    "batch_budget_reservation_repair.v1"
)
FIXED_HOLD_REPLAY_BUDGET_POLICY_ID = (
    "fixed_hold_replay.shared_family_cache.v2"
)
FIXED_HOLD_REPLAY_BUDGET_REPAIR_REASON = (
    "release identical producer-sized reservations from completed "
    "cache-consumer Jobs"
)
FIXED_HOLD_REPLAY_PRODUCER_BUDGET = {
    "compute_seconds": 3_600,
    "wall_seconds": 5_400,
}
FIXED_HOLD_REPLAY_CONSUMER_BUDGET = {
    "compute_seconds": 900,
    "wall_seconds": 1_440,
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _budget(name: str, value: object) -> dict[str, int]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"compute_seconds", "wall_seconds"}
        or any(
            type(value[field]) is not int or value[field] <= 0
            for field in ("compute_seconds", "wall_seconds")
        )
    ):
        raise ValueError(f"{name} must contain positive compute and wall bounds")
    return {
        "compute_seconds": value["compute_seconds"],
        "wall_seconds": value["wall_seconds"],
    }


def batch_budget_reservation_repair_manifest(
    *,
    batch_id: str,
    frozen_budget_ceiling: Mapping[str, int],
    declared_job_budgets: Mapping[str, Mapping[str, int]],
    corrected_job_budgets: Mapping[str, Mapping[str, int]],
    job_implementation_identities: Mapping[str, str],
    policy_id: str,
    reason: str,
) -> dict[str, object]:
    """Build one exact reduction-only reservation correction manifest."""

    _ascii("batch_id", batch_id)
    policy = _ascii("budget repair policy", policy_id)
    explanation = _ascii("budget repair reason", reason)
    ceiling = _budget("frozen Batch ceiling", frozen_budget_ceiling)
    if (
        not declared_job_budgets
        or set(declared_job_budgets) != set(corrected_job_budgets)
        or set(declared_job_budgets) != set(job_implementation_identities)
    ):
        raise ValueError("budget repair Job bindings are incomplete")
    rows: list[dict[str, object]] = []
    declared_totals = {"compute_seconds": 0, "wall_seconds": 0}
    corrected_totals = {"compute_seconds": 0, "wall_seconds": 0}
    reduced = False
    for job_id in sorted(declared_job_budgets):
        _ascii("budget repair Job id", job_id)
        implementation_identity = _ascii(
            "budget repair implementation identity",
            job_implementation_identities[job_id],
        )
        declared = _budget(
            "declared Job budget",
            declared_job_budgets[job_id],
        )
        corrected = _budget(
            "corrected Job budget",
            corrected_job_budgets[job_id],
        )
        if any(
            corrected[field] > declared[field]
            for field in ("compute_seconds", "wall_seconds")
        ):
            raise ValueError("budget repair cannot increase a Job reservation")
        reduced = reduced or corrected != declared
        for field in ("compute_seconds", "wall_seconds"):
            declared_totals[field] += declared[field]
            corrected_totals[field] += corrected[field]
        rows.append(
            {
                "corrected_budget": corrected,
                "declared_budget": declared,
                "implementation_identity": implementation_identity,
                "job_id": job_id,
            }
        )
    if not reduced:
        raise ValueError("budget repair must release an over-reservation")
    if any(
        corrected_totals[field] > ceiling[field]
        for field in ("compute_seconds", "wall_seconds")
    ):
        raise ValueError("corrected reservations exceed the frozen Batch ceiling")
    return {
        "batch_id": batch_id,
        "completed_job_count": len(rows),
        "corrected_reserved_totals": corrected_totals,
        "frozen_budget_ceiling": ceiling,
        "job_reservations": rows,
        "policy_id": policy,
        "prior_reserved_totals": declared_totals,
        "reason": explanation,
        "schema": BATCH_BUDGET_RESERVATION_REPAIR_SCHEMA,
        "scientific_trial_delta": 0,
    }


def registered_batch_budget_for_output_classes(
    *,
    policy_id: str,
    output_classes: Mapping[str, str],
) -> dict[str, int]:
    """Resolve a Job reservation through the closed production policy."""

    if policy_id != FIXED_HOLD_REPLAY_BUDGET_POLICY_ID:
        raise ValueError("Batch budget repair policy is not registered")
    if (
        not output_classes
        or any(
            type(name) is not str
            or type(output_class) is not str
            or output_class
            not in {"durable_evidence", "reproducible_cache", "transient"}
            for name, output_class in output_classes.items()
        )
    ):
        raise ValueError("Batch budget repair output classes are invalid")
    cache_count = tuple(output_classes.values()).count("reproducible_cache")
    if cache_count > 1:
        raise ValueError("Batch budget repair Job has multiple family caches")
    selected = (
        FIXED_HOLD_REPLAY_PRODUCER_BUDGET
        if cache_count == 1
        else FIXED_HOLD_REPLAY_CONSUMER_BUDGET
    )
    return dict(selected)


__all__ = [
    "BATCH_BUDGET_RESERVATION_REPAIR_SCHEMA",
    "FIXED_HOLD_REPLAY_BUDGET_POLICY_ID",
    "FIXED_HOLD_REPLAY_BUDGET_REPAIR_REASON",
    "FIXED_HOLD_REPLAY_CONSUMER_BUDGET",
    "FIXED_HOLD_REPLAY_PRODUCER_BUDGET",
    "batch_budget_reservation_repair_manifest",
    "registered_batch_budget_for_output_classes",
]
