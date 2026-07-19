from __future__ import annotations

import inspect

import pytest

from axiom_rift.operations.prospective_architecture_projection import (
    PROJECTION_SCHEMA,
    ProspectiveArchitectureProjectionError,
    projection_payload,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.positive_direction_sleeve_chassis import (
    PositiveDirectionSleeveConfiguration,
    positive_direction_sleeve_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (
    UNRESTRICTED_CONTROL,
    SleeveLossSkipRiskConfiguration,
    sleeve_loss_skip_risk_executable,
)
from axiom_rift.storage.index import IndexRecord


def _study_record(executable, *, study_id: str) -> IndexRecord:
    chassis = ArchitectureChassisSpec.from_executable(executable)
    return IndexRecord(
        kind="study-open",
        record_id=study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint="a" * 64,
        payload={
            "controlled_chassis": {
                "architecture": chassis.to_identity_payload(),
                "baseline_executable": executable.to_identity_payload(),
            },
            "system_architecture_family": chassis.identity,
        },
    )


def test_writer_groups_historical_implementation_variants_by_semantics() -> None:
    first = positive_direction_sleeve_executable(
        PositiveDirectionSleeveConfiguration("dual_positive_direction_slots")
    )
    second = sleeve_loss_skip_risk_executable(
        SleeveLossSkipRiskConfiguration(UNRESTRICTED_CONTROL)
    )
    assert ArchitectureChassisSpec.from_executable(first).identity != (
        ArchitectureChassisSpec.from_executable(second).identity
    )

    writer = object.__new__(StateWriter)
    first_family = writer._study_resolved_architecture_family(
        index=None,
        study=_study_record(first, study_id="STU-FIRST"),
    )
    second_family = writer._study_resolved_architecture_family(
        index=None,
        study=_study_record(second, study_id="STU-SECOND"),
    )
    assert first_family == second_family


def test_writer_connects_primary_control_guard_before_record_creation() -> None:
    source = inspect.getsource(StateWriter.record_study_diagnosis)
    assert source.index("require_primary_control_consistency") < source.index(
        "diagnosis_record ="
    )


def test_writer_connects_replay_forest_guard_before_decision_record() -> None:
    source = inspect.getsource(StateWriter.record_portfolio_decision)
    assert source.index("require_replay_forest_alternative") < source.index(
        'kind="portfolio-decision"'
    )


def test_prospective_projection_carries_only_still_current_legacy_axes() -> None:
    retained = "axis:retained"
    family = "architecture-family:" + "a" * 64
    projected = projection_payload(
        current_axis_identities={retained},
        derived_families={},
        prior_payload={
            "axis_families": {
                retained: family,
                "axis:removed": "architecture-family:" + "b" * 64,
            },
            "schema": PROJECTION_SCHEMA,
        },
    )
    assert projected == {
        "axis_families": {retained: family},
        "schema": PROJECTION_SCHEMA,
    }


def test_prospective_projection_rejects_family_rewrite_for_same_axis() -> None:
    axis = "axis:immutable"
    with pytest.raises(
        ProspectiveArchitectureProjectionError,
        match="family changed without a new identity",
    ):
        projection_payload(
            current_axis_identities={axis},
            derived_families={axis: "architecture-family:" + "b" * 64},
            prior_payload={
                "axis_families": {
                    axis: "architecture-family:" + "a" * 64,
                },
                "schema": PROJECTION_SCHEMA,
            },
        )
