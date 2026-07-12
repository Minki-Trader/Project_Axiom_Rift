from __future__ import annotations
import unittest
from axiom_rift.research.chassis import ArchitectureChassisSpec,ControlledStudyChassis,validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.high_vol_dense_regime_chassis import high_vol_dense_regime_baseline,high_vol_dense_regime_configurations,high_vol_dense_regime_executable
class HighVolDenseRegimeChassisTests(unittest.TestCase):
    def test_subject_changes_only_regime_parameter(self)->None:
        baseline=high_vol_dense_regime_baseline();subject=high_vol_dense_regime_executable(high_vol_dense_regime_configurations()[1]);chassis=ControlledStudyChassis(baseline_executable=baseline,changed_domains=(ResearchLayer.REGIME,),controlled_domains=(ResearchLayer.FEATURE,ResearchLayer.LABEL,ResearchLayer.MODEL,ResearchLayer.SELECTOR,ResearchLayer.TRADE,ResearchLayer.LIFECYCLE,ResearchLayer.RISK,ResearchLayer.EXECUTION,ResearchLayer.SYNTHESIS),architecture=ArchitectureChassisSpec.from_executable(baseline));validate_controlled_executable(chassis.to_identity_payload(),subject)
if __name__=="__main__":unittest.main()
