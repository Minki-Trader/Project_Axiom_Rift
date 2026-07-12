from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.fold_train_target_role_chassis import fold_train_target_role_baseline, fold_train_target_role_configurations, fold_train_target_role_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.high_vol_target_reversal_chassis import high_vol_target_reversal_configurations, high_vol_target_reversal_executable


class FoldTrainTargetRoleTests(unittest.TestCase):
    def test_control_reuses_exact_stu0092_subject(self) -> None:
        self.assertEqual(fold_train_target_role_baseline().identity, high_vol_target_reversal_executable(high_vol_target_reversal_configurations()[1]).identity)

    def test_subject_changes_only_portfolio_and_risk(self) -> None:
        baseline = fold_train_target_role_baseline()
        control = ControlledStudyChassis(baseline_executable=baseline, changed_domains=(ResearchLayer.PORTFOLIO, ResearchLayer.RISK), controlled_domains=(ResearchLayer.CALIBRATION, ResearchLayer.EXECUTION, ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.LIFECYCLE, ResearchLayer.MODEL, ResearchLayer.REGIME, ResearchLayer.SELECTOR, ResearchLayer.SYNTHESIS, ResearchLayer.TRADE), architecture=ArchitectureChassisSpec.from_executable(baseline))
        subject = fold_train_target_role_executable(fold_train_target_role_configurations()[1])
        validate_controlled_executable(control.to_identity_payload(), subject)
        self.assertNotEqual(baseline.identity, subject.identity)


if __name__ == "__main__":
    unittest.main()
