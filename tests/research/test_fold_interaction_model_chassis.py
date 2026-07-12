from __future__ import annotations

import unittest

import numpy as np

from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.fold_interaction_model_chassis import (
    fold_interaction_model_baseline,
    fold_interaction_model_configurations,
    fold_interaction_model_executable,
    model_design,
)
from axiom_rift.research.governance import ResearchLayer


class FoldInteractionModelChassisTests(unittest.TestCase):
    def test_pairwise_profile_adds_ten_bounded_terms(self) -> None:
        values = np.arange(20, dtype=float).reshape(4, 5)
        self.assertEqual(model_design(values, "linear_ridge_control").shape, (4, 5))
        self.assertEqual(model_design(values, "pairwise_interaction_ridge").shape, (4, 15))

    def test_subject_changes_only_the_model_parameter(self) -> None:
        baseline = fold_interaction_model_baseline()
        subject = fold_interaction_model_executable(
            next(
                value
                for value in fold_interaction_model_configurations()
                if value.profile == "pairwise_interaction_ridge"
            )
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.MODEL,),
            controlled_domains=(
                ResearchLayer.FEATURE,
                ResearchLayer.LABEL,
                ResearchLayer.SELECTOR,
                ResearchLayer.TRADE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.RISK,
                ResearchLayer.EXECUTION,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )

        validate_controlled_executable(chassis.to_identity_payload(), subject)
        self.assertEqual(
            {component.identity for component in baseline.components},
            {component.identity for component in subject.components},
        )


if __name__ == "__main__":
    unittest.main()
