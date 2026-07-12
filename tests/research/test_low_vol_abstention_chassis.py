from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.low_vol_abstention_chassis import low_vol_abstention_baseline, low_vol_abstention_configurations, low_vol_abstention_executable
from axiom_rift.research.session_dense_positive_sleeve_chassis import session_dense_positive_sleeve_configurations, session_dense_positive_sleeve_executable


class LowVolAbstentionTests(unittest.TestCase):
    def test_control_reuses_exact_stu0090_subject(self) -> None:
        self.assertEqual(low_vol_abstention_baseline().identity, session_dense_positive_sleeve_executable(session_dense_positive_sleeve_configurations()[1]).identity)

    def test_subject_changes_only_portfolio_and_risk(self) -> None:
        baseline = low_vol_abstention_baseline()
        control = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.PORTFOLIO, ResearchLayer.RISK),
            controlled_domains=(ResearchLayer.CALIBRATION, ResearchLayer.EXECUTION, ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.LIFECYCLE, ResearchLayer.MODEL, ResearchLayer.REGIME, ResearchLayer.SELECTOR, ResearchLayer.SYNTHESIS, ResearchLayer.TRADE),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        subject = low_vol_abstention_executable(low_vol_abstention_configurations()[1])
        validate_controlled_executable(control.to_identity_payload(), subject)
        self.assertNotEqual(baseline.identity, subject.identity)


if __name__ == "__main__":
    unittest.main()
