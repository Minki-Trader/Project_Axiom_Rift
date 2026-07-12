from __future__ import annotations
import unittest
from axiom_rift.research.chassis import ArchitectureChassisSpec,ControlledStudyChassis,validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.positive_direction_sleeve_chassis import positive_direction_sleeve_baseline,positive_direction_sleeve_configurations,positive_direction_sleeve_executable
class PositiveDirectionSleeveTests(unittest.TestCase):
    def test_subject_changes_only_portfolio_and_risk(self)->None:
        baseline=positive_direction_sleeve_baseline();architecture=ArchitectureChassisSpec.from_executable(baseline);control=ControlledStudyChassis(baseline_executable=baseline,changed_domains=(ResearchLayer.PORTFOLIO,ResearchLayer.RISK),controlled_domains=(ResearchLayer.CALIBRATION,ResearchLayer.EXECUTION,ResearchLayer.FEATURE,ResearchLayer.LABEL,ResearchLayer.LIFECYCLE,ResearchLayer.MODEL,ResearchLayer.REGIME,ResearchLayer.SELECTOR,ResearchLayer.SYNTHESIS,ResearchLayer.TRADE),architecture=architecture);subject=positive_direction_sleeve_executable(positive_direction_sleeve_configurations()[1]);validate_controlled_executable(control.to_identity_payload(),subject);self.assertNotEqual(baseline.identity,subject.identity)
if __name__=="__main__":unittest.main()
