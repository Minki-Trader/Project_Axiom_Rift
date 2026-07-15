"""Pure projection and validation for bounded architecture-review direction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from axiom_rift.research.governance import (
    ArchitectureContinuationDirection,
    ArchitectureContinuationMode,
)


class ArchitectureReviewDirectionError(ValueError):
    """A continuation direction is malformed, stale, or not obeyed."""


_COMMON_FIELDS = frozenset(
    {
        "architecture_continuation_mode",
        "architecture_review_id",
        "architecture_review_trigger_id",
        "constraint_source_id",
        "covered_diagnosis_ids",
        "required_architecture_family",
    }
)
_MODE_FIELDS = frozenset(
    {
        "required_followup_layers",
        "required_target_axis_identity",
        "required_target_axis_ids",
    }
)
ARCHITECTURE_CONTINUATION_ACTION_FIELDS = _COMMON_FIELDS | _MODE_FIELDS


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ArchitectureReviewDirectionError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ArchitectureReviewDirectionError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise ArchitectureReviewDirectionError(
            f"{name} must use the {prefix} namespace"
        )
    _digest(name, text.removeprefix(prefix))
    return text


def _canonical_ascii_list(
    name: str,
    value: object,
    *,
    prefix: str | None = None,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ArchitectureReviewDirectionError(f"{name} must be a non-empty list")
    items = tuple(_ascii(name, item) for item in value)
    if items != tuple(sorted(set(items))):
        raise ArchitectureReviewDirectionError(f"{name} must be sorted and unique")
    if prefix is not None:
        for item in items:
            _identity(name, item, prefix)
    return items


def direction_from_identity_payload(
    payload: object,
) -> ArchitectureContinuationDirection:
    """Rebuild the exact closed direction carried by an architecture review."""

    if not isinstance(payload, Mapping):
        raise ArchitectureReviewDirectionError("continuation direction is absent")
    mode_value = payload.get("mode")
    try:
        mode = ArchitectureContinuationMode(mode_value)
    except (TypeError, ValueError) as exc:
        raise ArchitectureReviewDirectionError(
            "continuation direction mode is invalid"
        ) from exc
    common = {
        "covered_diagnosis_ids",
        "mode",
        "reviewed_architecture_family",
        "schema",
        "trigger_record_id",
    }
    specific = (
        {"target_axis_id", "target_axis_identity"}
        if mode is ArchitectureContinuationMode.EXISTING_AXIS
        else {"required_research_layer"}
    )
    if set(payload) != common | specific:
        raise ArchitectureReviewDirectionError(
            "continuation direction schema is not exact"
        )
    if payload.get("schema") != "architecture_continuation_direction.v1":
        raise ArchitectureReviewDirectionError(
            "continuation direction schema is unsupported"
        )
    from axiom_rift.research.governance import (
        ResearchGovernanceError,
        ResearchLayer,
    )

    try:
        return ArchitectureContinuationDirection(
            mode=mode,
            reviewed_architecture_family=payload["reviewed_architecture_family"],
            trigger_record_id=payload["trigger_record_id"],
            covered_diagnosis_ids=tuple(payload["covered_diagnosis_ids"]),
            target_axis_id=payload.get("target_axis_id"),
            target_axis_identity=payload.get("target_axis_identity"),
            required_research_layer=(
                None
                if mode is ArchitectureContinuationMode.EXISTING_AXIS
                else ResearchLayer(payload["required_research_layer"])
            ),
        )
    except (KeyError, TypeError, ValueError, ResearchGovernanceError) as exc:
        raise ArchitectureReviewDirectionError(
            "continuation direction payload is malformed"
        ) from exc


@dataclass(frozen=True, slots=True)
class ArchitectureContinuationConstraint:
    """Closed scheduler projection derived from one v2 ArchitectureReview."""

    mode: ArchitectureContinuationMode
    architecture_review_id: str
    trigger_record_id: str
    covered_diagnosis_ids: tuple[str, ...]
    required_architecture_family: str
    required_target_axis_ids: tuple[str, ...] = ()
    required_target_axis_identity: str | None = None
    required_research_layer: str | None = None

    def to_action_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "architecture_continuation_mode": self.mode.value,
            "architecture_review_id": self.architecture_review_id,
            "architecture_review_trigger_id": self.trigger_record_id,
            "constraint_source_id": self.architecture_review_id,
            "covered_diagnosis_ids": list(self.covered_diagnosis_ids),
            "required_architecture_family": self.required_architecture_family,
        }
        if self.required_target_axis_ids:
            fields["required_target_axis_ids"] = list(
                self.required_target_axis_ids
            )
        if self.required_target_axis_identity is not None:
            fields["required_target_axis_identity"] = (
                self.required_target_axis_identity
            )
        if self.required_research_layer is not None:
            fields["required_followup_layers"] = [self.required_research_layer]
        return fields

    def with_materialized_targets(
        self,
        target_axis_ids: tuple[str, ...],
    ) -> ArchitectureContinuationConstraint:
        if self.mode is not ArchitectureContinuationMode.NEW_MECHANISM:
            raise ArchitectureReviewDirectionError(
                "only a new-mechanism direction can materialize target axes"
            )
        normalized = tuple(sorted(_ascii("materialized target axis", item) for item in target_axis_ids))
        if not normalized or len(set(normalized)) != len(normalized):
            raise ArchitectureReviewDirectionError(
                "materialized target axes must be non-empty and unique"
            )
        return ArchitectureContinuationConstraint(
            mode=self.mode,
            architecture_review_id=self.architecture_review_id,
            trigger_record_id=self.trigger_record_id,
            covered_diagnosis_ids=self.covered_diagnosis_ids,
            required_architecture_family=self.required_architecture_family,
            required_target_axis_ids=normalized,
            required_research_layer=self.required_research_layer,
        )


def constraint_from_direction(
    *,
    architecture_review_id: str,
    direction: ArchitectureContinuationDirection,
) -> ArchitectureContinuationConstraint:
    """Project a typed expert direction into exact next-action constraints."""

    review_id = _identity(
        "architecture review identity",
        architecture_review_id,
        "architecture-review:",
    )
    if direction.mode is ArchitectureContinuationMode.EXISTING_AXIS:
        assert direction.target_axis_id is not None
        assert direction.target_axis_identity is not None
        return ArchitectureContinuationConstraint(
            mode=direction.mode,
            architecture_review_id=review_id,
            trigger_record_id=direction.trigger_record_id,
            covered_diagnosis_ids=direction.covered_diagnosis_ids,
            required_architecture_family=direction.reviewed_architecture_family,
            required_target_axis_ids=(direction.target_axis_id,),
            required_target_axis_identity=direction.target_axis_identity,
        )
    assert direction.required_research_layer is not None
    return ArchitectureContinuationConstraint(
        mode=direction.mode,
        architecture_review_id=review_id,
        trigger_record_id=direction.trigger_record_id,
        covered_diagnosis_ids=direction.covered_diagnosis_ids,
        required_architecture_family=direction.reviewed_architecture_family,
        required_research_layer=direction.required_research_layer.value,
    )


def constraint_from_action(
    action: Mapping[str, Any],
) -> ArchitectureContinuationConstraint | None:
    """Parse continuation fields without accepting partial or free-form shapes."""

    if "architecture_continuation_mode" not in action:
        stray = {
            "architecture_review_trigger_id",
            "covered_diagnosis_ids",
            "required_architecture_family",
            "required_target_axis_identity",
        }.intersection(action)
        if stray:
            raise ArchitectureReviewDirectionError(
                "architecture continuation constraint is incomplete"
            )
        return None
    if not _COMMON_FIELDS.issubset(action):
        raise ArchitectureReviewDirectionError(
            "architecture continuation constraint is incomplete"
        )
    try:
        mode = ArchitectureContinuationMode(action["architecture_continuation_mode"])
    except (TypeError, ValueError) as exc:
        raise ArchitectureReviewDirectionError(
            "architecture continuation mode is invalid"
        ) from exc
    review_id = _identity(
        "architecture review identity",
        action["architecture_review_id"],
        "architecture-review:",
    )
    if action["constraint_source_id"] != review_id:
        raise ArchitectureReviewDirectionError(
            "architecture continuation source differs from its review"
        )
    trigger_id = _digest(
        "architecture review trigger",
        action["architecture_review_trigger_id"],
    )
    diagnoses = _canonical_ascii_list(
        "covered diagnosis",
        action["covered_diagnosis_ids"],
        prefix="diagnosis:",
    )
    family = _identity(
        "required architecture family",
        action["required_architecture_family"],
        "architecture-family:",
    )
    target_ids = ()
    if "required_target_axis_ids" in action:
        target_ids = _canonical_ascii_list(
            "required target axis",
            action["required_target_axis_ids"],
        )
    target_identity = action.get("required_target_axis_identity")
    layers = action.get("required_followup_layers")
    if mode is ArchitectureContinuationMode.EXISTING_AXIS:
        if len(target_ids) != 1 or layers is not None:
            raise ArchitectureReviewDirectionError(
                "existing-axis continuation constraint is malformed"
            )
        typed_target_identity = _identity(
            "required target axis identity",
            target_identity,
            "axis:",
        )
        research_layer = None
    else:
        if target_identity is not None:
            raise ArchitectureReviewDirectionError(
                "new-mechanism continuation preselects an axis identity"
            )
        layer_values = _canonical_ascii_list("required followup layer", layers)
        if len(layer_values) != 1:
            raise ArchitectureReviewDirectionError(
                "new-mechanism continuation requires one research layer"
            )
        from axiom_rift.research.governance import ResearchLayer

        try:
            research_layer = ResearchLayer(layer_values[0]).value
        except ValueError as exc:
            raise ArchitectureReviewDirectionError(
                "new-mechanism continuation research layer is invalid"
            ) from exc
        typed_target_identity = None
    return ArchitectureContinuationConstraint(
        mode=mode,
        architecture_review_id=review_id,
        trigger_record_id=trigger_id,
        covered_diagnosis_ids=diagnoses,
        required_architecture_family=family,
        required_target_axis_ids=target_ids,
        required_target_axis_identity=typed_target_identity,
        required_research_layer=research_layer,
    )


def require_review_binding(
    constraint: ArchitectureContinuationConstraint,
    *,
    review_record_id: str,
    review_payload: Mapping[str, Any],
    trigger_payload: Mapping[str, Any],
) -> ArchitectureContinuationDirection:
    """Recompute exact review, trigger, family, and diagnosis authority."""

    if review_payload.get("schema") != "architecture_review.v2" or review_payload.get(
        "conclusion"
    ) != "bounded_same_architecture":
        raise ArchitectureReviewDirectionError(
            "bounded continuation does not bind a v2 architecture review"
        )
    direction = direction_from_identity_payload(
        review_payload.get("continuation_direction")
    )
    expected = constraint_from_direction(
        architecture_review_id=review_record_id,
        direction=direction,
    )
    if constraint.required_target_axis_ids and (
        direction.mode is ArchitectureContinuationMode.NEW_MECHANISM
    ):
        expected = expected.with_materialized_targets(
            constraint.required_target_axis_ids
        )
    if constraint != expected:
        raise ArchitectureReviewDirectionError(
            "architecture continuation projection differs from its review"
        )
    trigger_diagnoses = _canonical_ascii_list(
        "architecture review trigger diagnosis",
        trigger_payload.get("diagnosis_ids"),
        prefix="diagnosis:",
    )
    if (
        trigger_payload.get("schema") != "architecture_review_trigger.v1"
        or trigger_payload.get("system_architecture_family")
        != constraint.required_architecture_family
        or direction.trigger_record_id != constraint.trigger_record_id
        or direction.covered_diagnosis_ids != trigger_diagnoses
        or review_payload.get("covered_diagnosis_ids") != list(trigger_diagnoses)
    ):
        raise ArchitectureReviewDirectionError(
            "architecture continuation differs from its exact trigger"
        )
    return direction


def require_existing_axis_binding(
    constraint: ArchitectureContinuationConstraint,
    *,
    axes_by_id: Mapping[str, Mapping[str, Any]],
    selectable_axis_ids: frozenset[str],
    resolved_architecture_families: Mapping[str, str],
) -> None:
    """Check the expert-selected current axis without using coverage as a veto."""

    if constraint.mode is not ArchitectureContinuationMode.EXISTING_AXIS:
        return
    target_id = constraint.required_target_axis_ids[0]
    target = axes_by_id.get(target_id)
    if (
        target is None
        or target_id not in selectable_axis_ids
        or target.get("axis_identity") != constraint.required_target_axis_identity
        or resolved_architecture_families.get(target_id)
        != constraint.required_architecture_family
    ):
        raise ArchitectureReviewDirectionError(
            "bounded existing axis is absent, stale, blocked, or outside the reviewed family"
        )


def require_decision_direction(
    constraint: ArchitectureContinuationConstraint,
    *,
    action: str,
    target_axis_id: str,
    target_axis_identity: str,
    target_architecture_family: str,
) -> None:
    """Require one Decision to follow the exact continuation phase."""

    if target_architecture_family != constraint.required_architecture_family:
        raise ArchitectureReviewDirectionError(
            "Portfolio Decision left its required reviewed architecture family"
        )
    if constraint.mode is ArchitectureContinuationMode.EXISTING_AXIS:
        if (
            action in {"new_mechanism", "preserve", "prune"}
            or target_axis_id != constraint.required_target_axis_ids[0]
            or target_axis_identity != constraint.required_target_axis_identity
        ):
            raise ArchitectureReviewDirectionError(
                "Portfolio Decision bypasses its exact bounded existing axis"
            )
        return
    if constraint.required_target_axis_ids:
        if action == "new_mechanism" or target_axis_id not in set(
            constraint.required_target_axis_ids
        ):
            raise ArchitectureReviewDirectionError(
                "Portfolio Decision bypasses its materialized bounded mechanism"
            )
    elif action != "new_mechanism":
        raise ArchitectureReviewDirectionError(
            "bounded new-mechanism direction requires new_mechanism"
        )


def eligible_new_mechanism_axes(
    constraint: ArchitectureContinuationConstraint,
    *,
    added_axes: Mapping[str, Mapping[str, Any]],
    resolved_architecture_families: Mapping[str, str],
) -> tuple[str, ...]:
    """Filter added axes by the expert layer and exact reviewed family."""

    if constraint.mode is not ArchitectureContinuationMode.NEW_MECHANISM:
        raise ArchitectureReviewDirectionError(
            "existing-axis continuation cannot admit a new mechanism"
        )
    eligible = tuple(
        sorted(
            axis_id
            for axis_id, axis in added_axes.items()
            if axis.get("primary_research_layer")
            == constraint.required_research_layer
            and resolved_architecture_families.get(axis_id)
            == constraint.required_architecture_family
        )
    )
    if not eligible:
        raise ArchitectureReviewDirectionError(
            "new mechanism does not satisfy its bounded architecture direction"
        )
    return eligible


def required_quant_team_basis(
    constraint: ArchitectureContinuationConstraint,
) -> frozenset[tuple[str, str]]:
    return frozenset(
        {
            ("architecture-review", constraint.architecture_review_id),
            ("architecture-review-trigger", constraint.trigger_record_id),
            *(
                ("study-diagnosis", diagnosis_id)
                for diagnosis_id in constraint.covered_diagnosis_ids
            ),
        }
    )


__all__ = [
    "ARCHITECTURE_CONTINUATION_ACTION_FIELDS",
    "ArchitectureContinuationConstraint",
    "ArchitectureReviewDirectionError",
    "constraint_from_action",
    "constraint_from_direction",
    "direction_from_identity_payload",
    "eligible_new_mechanism_axes",
    "require_decision_direction",
    "require_existing_axis_binding",
    "require_review_binding",
    "required_quant_team_basis",
]
