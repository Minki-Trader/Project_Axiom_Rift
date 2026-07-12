from __future__ import annotations
import unittest
from axiom_rift.research.chassis import ArchitectureChassisSpec,ControlledStudyChassis,validate_controlled_executable
from axiom_rift.research.dense_short_synthesis_chassis import dense_short_synthesis_baseline,dense_short_synthesis_configurations,dense_short_synthesis_executable
from axiom_rift.research.governance import ResearchLayer
class DenseShortSynthesisChassisTests(unittest.TestCase):
    def test_subject_changes_declared_synthesis_domains(self)->None:
        baseline=dense_short_synthesis_baseline();subject=dense_short_synthesis_executable(dense_short_synthesis_configurations()[1])
        chassis=ControlledStudyChassis(baseline_executable=baseline,changed_domains=(ResearchLayer.LABEL,ResearchLayer.SELECTOR,ResearchLayer.LIFECYCLE,ResearchLayer.SYNTHESIS),controlled_domains=(ResearchLayer.FEATURE,ResearchLayer.MODEL,ResearchLayer.TRADE,ResearchLayer.RISK,ResearchLayer.EXECUTION),architecture=ArchitectureChassisSpec.from_executable(baseline))
        validate_controlled_executable(chassis.to_identity_payload(),subject)
if __name__=="__main__":unittest.main()
