from __future__ import annotations
import unittest
from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.monthly_loss_lock_risk_chassis import monthly_loss_lock_risk_baseline, monthly_loss_lock_risk_configurations, monthly_loss_lock_risk_executable


class MonthlyLossLockRiskChassisTests(unittest.TestCase):
    def test_subject_changes_only_declared_risk_domain(self) -> None:
        baseline = monthly_loss_lock_risk_baseline()
        subject = monthly_loss_lock_risk_executable(monthly_loss_lock_risk_configurations()[1])
        chassis = ControlledStudyChassis(baseline_executable=baseline, changed_domains=(ResearchLayer.RISK,), controlled_domains=(ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.MODEL, ResearchLayer.SELECTOR, ResearchLayer.REGIME, ResearchLayer.TRADE, ResearchLayer.LIFECYCLE, ResearchLayer.EXECUTION, ResearchLayer.SYNTHESIS), architecture=ArchitectureChassisSpec.from_executable(baseline))
        validate_controlled_executable(chassis.to_identity_payload(), subject)


if __name__ == "__main__":
    unittest.main()
