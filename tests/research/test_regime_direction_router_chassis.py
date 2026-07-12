from __future__ import annotations
import unittest
from axiom_rift.research.chassis import ArchitectureChassisSpec,ControlledStudyChassis,validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.regime_direction_router_chassis import regime_direction_router_baseline,regime_direction_router_configurations,regime_direction_router_executable
class RegimeDirectionRouterChassisTests(unittest.TestCase):
    def test_subject_changes_declared_router_domains(self)->None:
        baseline=regime_direction_router_baseline();subject=regime_direction_router_executable(regime_direction_router_configurations()[1]);chassis=ControlledStudyChassis(baseline_executable=baseline,changed_domains=(ResearchLayer.REGIME,ResearchLayer.TRADE,ResearchLayer.SYNTHESIS),controlled_domains=(ResearchLayer.FEATURE,ResearchLayer.LABEL,ResearchLayer.MODEL,ResearchLayer.SELECTOR,ResearchLayer.LIFECYCLE,ResearchLayer.RISK,ResearchLayer.EXECUTION),architecture=ArchitectureChassisSpec.from_executable(baseline));validate_controlled_executable(chassis.to_identity_payload(),subject)
if __name__=="__main__":unittest.main()
