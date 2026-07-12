from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.structural_break_discovery import compute_structural_break_score,executable_configuration_map,structural_break_configurations
from axiom_rift.research.structural_break_study import build_structural_break_validation_plan
class StructuralBreakTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(structural_break_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_feature_is_prefix_invariant(self)->None:
        rows=1800;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum(np.sin(np.arange(rows)/17)+0.1);frame=pd.DataFrame({"time":time,"close":close});full=compute_structural_break_score(frame,"mean_shift_cusum_576");prefix=compute_structural_break_score(frame.iloc[:1600].copy(),"mean_shift_cusum_576")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:1600],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fifth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_structural_break_validation_plan(eid)["mission_id"],"MIS-0005")
if __name__=="__main__":unittest.main()
