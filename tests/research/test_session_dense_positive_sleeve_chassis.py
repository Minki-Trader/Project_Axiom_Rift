from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.session_dense_positive_sleeve_chassis import session_dense_positive_sleeve_baseline, session_dense_positive_sleeve_configurations, session_dense_positive_sleeve_executable


class SessionDensePositiveSleeveTests(unittest.TestCase):
    def test_subject_changes_only_registered_portfolio_surface(self) -> None:
        baseline = session_dense_positive_sleeve_baseline()
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        control = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.PORTFOLIO, ResearchLayer.REGIME, ResearchLayer.RISK, ResearchLayer.SELECTOR),
            controlled_domains=(ResearchLayer.CALIBRATION, ResearchLayer.EXECUTION, ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.LIFECYCLE, ResearchLayer.MODEL, ResearchLayer.SYNTHESIS, ResearchLayer.TRADE),
            architecture=architecture,
        )
        subject = session_dense_positive_sleeve_executable(session_dense_positive_sleeve_configurations()[1])
        validate_controlled_executable(control.to_identity_payload(), subject)
        self.assertNotEqual(baseline.identity, subject.identity)

    def test_exact_structural_extreme_is_frozen(self) -> None:
        control, subject = session_dense_positive_sleeve_configurations()
        self.assertEqual((control.target_quantile_bp, control.target_session_policy), (9750, "all_broker_hours"))
        self.assertEqual((subject.target_quantile_bp, subject.target_session_policy), (9000, "broker_15_22_only"))


if __name__ == "__main__":
    unittest.main()
