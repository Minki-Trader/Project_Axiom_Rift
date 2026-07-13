from __future__ import annotations

import unittest

import numpy as np

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.event_direction_meta_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    apply_event_direction_actions,
    event_direction_meta_baseline,
    event_direction_meta_configurations,
    event_direction_meta_executable,
)
from axiom_rift.research.event_direction_meta_discovery import (
    EVENT_STATE_FEATURE_NAMES,
    event_state_matrix,
)
from axiom_rift.research.event_direction_meta_study import (
    build_event_direction_meta_validation_plan,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.high_vol_target_reversal_chassis import (
    high_vol_target_reversal_configurations,
    high_vol_target_reversal_executable,
)
from axiom_rift.research.validation import require_supported_evaluation_schema


class EventDirectionMetaChassisTests(unittest.TestCase):
    def test_control_reuses_exact_stu0092_subject(self) -> None:
        self.assertEqual(
            event_direction_meta_baseline().identity,
            high_vol_target_reversal_executable(
                high_vol_target_reversal_configurations()[1]
            ).identity,
        )
        self.assertEqual(SELECTION_TOTAL_EXPOSURES, 593)

    def test_subject_changes_exact_declared_layers(self) -> None:
        baseline = event_direction_meta_baseline()
        controlled = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(
                ResearchLayer.LABEL,
                ResearchLayer.MODEL,
                ResearchLayer.SYNTHESIS,
                ResearchLayer.TRADE,
            ),
            controlled_domains=(
                ResearchLayer.CALIBRATION,
                ResearchLayer.EXECUTION,
                ResearchLayer.FEATURE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.PORTFOLIO,
                ResearchLayer.REGIME,
                ResearchLayer.RISK,
                ResearchLayer.SELECTOR,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        subject = event_direction_meta_executable(
            event_direction_meta_configurations()[1]
        )
        validate_controlled_executable(controlled.to_identity_payload(), subject)
        self.assertNotEqual(baseline.identity, subject.identity)

    def test_direction_action_preserves_activity_and_forbids_abstention(self) -> None:
        score = np.array([[1.0, -2.0], [0.0, np.nan], [-3.0, 4.0]])
        result = apply_event_direction_actions(
            score,
            np.array([1, -1, -1]),
            np.array([-1, 1, 1]),
        )
        np.testing.assert_array_equal(np.abs(result), np.abs(score))
        with self.assertRaisesRegex(ValueError, "follow or reverse"):
            apply_event_direction_actions(
                score,
                np.array([1, 0, -1]),
                np.array([-1, 1, 1]),
            )

    def test_event_state_has_fixed_finite_prefix_invariant_encoding(self) -> None:
        raw = np.arange(40, dtype=float).reshape(8, 5)
        raw[2, 1] = np.nan
        score = np.column_stack(
            (np.linspace(-2.0, 2.0, 8), np.linspace(1.0, -1.0, 8))
        )
        score[3, 1] = np.nan
        volatility = np.linspace(0.1, 0.8, 8)
        full = event_state_matrix(
            raw,
            score,
            volatility,
            (0.3, 0.6),
            slot_index=1,
        )
        prefix = event_state_matrix(
            raw[:6],
            score[:6],
            volatility[:6],
            (0.3, 0.6),
            slot_index=1,
        )
        self.assertEqual(full.shape[1], len(EVENT_STATE_FEATURE_NAMES))
        self.assertTrue(np.isfinite(full).all())
        np.testing.assert_array_equal(full[:6], prefix)

    def test_validator_profile_and_invariance_criteria_are_registered(self) -> None:
        self.assertEqual(
            require_supported_evaluation_schema(
                "event_direction_meta_evaluation.v1"
            ),
            "event_direction_meta_evaluation.v1",
        )
        subject = event_direction_meta_executable(
            event_direction_meta_configurations()[1]
        )
        plan = build_event_direction_meta_validation_plan(
            subject.identity,
            mission_id="MIS-0006",
        )
        criteria = {item["criterion_id"] for item in plan["criteria"]}
        self.assertIn("C06-event-intent-schedule-invariance", criteria)
        self.assertIn("C10-no-direction-abstention", criteria)


if __name__ == "__main__":
    unittest.main()
