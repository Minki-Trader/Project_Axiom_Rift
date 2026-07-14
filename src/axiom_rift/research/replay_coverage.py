"""Exact criterion-coverage proof for bounded historical replay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


_DEFINITION_FIELDS = (
    "claim_id",
    "criterion_id",
    "decision_role",
    "metric",
    "operator",
    "threshold",
)


def validated_recomputed_criterion_ids(
    facts: Mapping[str, object],
    *,
    expected_evidence_modes: tuple[str, ...],
    expected_criteria: Sequence[Mapping[str, object]],
    context: str,
) -> tuple[str, ...]:
    """Return exact coverage only for complete and evaluable replay facts.

    A failed economic, control, or stability threshold is still a valid
    recomputation.  Missing comparisons, drifted definitions, or failed
    validity evidence are not.  This keeps scientific falsification distinct
    from engineering or evidence failure.
    """

    label = context if type(context) is str and context.isascii() else "replay"
    if not isinstance(facts, Mapping):
        raise ValueError(f"{label} facts must be a mapping")
    modes = facts.get("executed_evidence_modes")
    if not isinstance(modes, (list, tuple)) or tuple(modes) != (
        expected_evidence_modes
    ):
        raise ValueError(f"{label} evidence modes are incomplete")
    adjudication = facts.get("scientific_adjudication")
    if (
        not isinstance(adjudication, Mapping)
        or adjudication.get("schema") != "scientific_adjudication.v1"
        or adjudication.get("evaluable") is not True
        or adjudication.get("invalid_metrics") != []
    ):
        raise ValueError(f"{label} adjudication is not fully evaluable")
    raw_criteria = adjudication.get("criteria")
    if not isinstance(raw_criteria, list) or any(
        not isinstance(item, Mapping) for item in raw_criteria
    ):
        raise ValueError(f"{label} criterion facts are malformed")

    definitions: dict[str, Mapping[str, object]] = {}
    for item in expected_criteria:
        if not isinstance(item, Mapping):
            raise ValueError(f"{label} expected criteria are malformed")
        criterion_id = item.get("criterion_id")
        if type(criterion_id) is not str or criterion_id in definitions:
            raise ValueError(f"{label} expected criterion identity is ambiguous")
        definitions[criterion_id] = item
    expected_ids = tuple(sorted(definitions))

    observed: dict[str, Mapping[str, object]] = {}
    for item in raw_criteria:
        criterion_id = item.get("criterion_id")
        if type(criterion_id) is not str or criterion_id in observed:
            raise ValueError(f"{label} criterion identity is ambiguous")
        observed[criterion_id] = item
    if tuple(sorted(observed)) != expected_ids:
        raise ValueError(f"{label} criterion inventory is incomplete")

    for criterion_id, item in observed.items():
        definition = definitions[criterion_id]
        for field in _DEFINITION_FIELDS:
            if item.get(field) != definition.get(field):
                raise ValueError(
                    f"{label} criterion definition drifted: {criterion_id}"
                )
        comparison = item.get("comparison_state", item.get("state"))
        if comparison not in {"passed", "failed"} or type(
            item.get("value")
        ) is not int:
            raise ValueError(
                f"{label} criterion was not recomputed: {criterion_id}"
            )
        role = definition.get("decision_role")
        expected_scientific = (
            "diagnostic"
            if role == "risk_diagnostic"
            else (
                "invalid"
                if role == "validity" and comparison == "failed"
                else "supported"
                if comparison == "passed"
                else "contradicted"
            )
        )
        if item.get("scientific_state") != expected_scientific:
            raise ValueError(
                f"{label} scientific state drifted: {criterion_id}"
            )
        if expected_scientific == "invalid":
            raise ValueError(
                f"{label} validity evidence failed: {criterion_id}"
            )
    return expected_ids


__all__ = ["validated_recomputed_criterion_ids"]
