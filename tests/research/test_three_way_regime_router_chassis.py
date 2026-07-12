from __future__ import annotations
import unittest
from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.three_way_regime_router_chassis import three_way_regime_router_baseline, three_way_regime_router_configurations, three_way_regime_router_executable


class ThreeWayRegimeRouterChassisTests(unittest.TestCase):
    def test_subject_changes_declared_router_domains(self) -> None:
        baseline = three_way_regime_router_baseline()
        subject = three_way_regime_router_executable(three_way_regime_router_configurations()[1])
        chassis = ControlledStudyChassis(baseline_executable=baseline, changed_domains=(ResearchLayer.REGIME, ResearchLayer.TRADE, ResearchLayer.SYNTHESIS), controlled_domains=(ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.MODEL, ResearchLayer.SELECTOR, ResearchLayer.LIFECYCLE, ResearchLayer.RISK, ResearchLayer.EXECUTION), architecture=ArchitectureChassisSpec.from_executable(baseline))
        validate_controlled_executable(chassis.to_identity_payload(), subject)


if __name__ == "__main__":
    unittest.main()
