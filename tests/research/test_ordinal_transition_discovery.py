from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.ordinal_transition_discovery import compute_ordinal_score,executable_configuration_map,ordinal_configurations
from axiom_rift.research.ordinal_transition_study import build_ordinal_validation_plan
class OrdinalTransitionTests(unittest.TestCase):
    def test_surface_has_six_unique_executables(self)->None:self.assertEqual(len(ordinal_configurations()),6);self.assertEqual(len(executable_configuration_map()),6)
    def test_ordinal_is_prefix_invariant(self)->None:
        rows=180;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum(np.sin(np.arange(rows)/7));frame=pd.DataFrame({"time":time,"open":close-.2,"high":close+1,"low":close-1,"close":close});full=compute_ordinal_score(frame,"ordinal_extreme_8");prefix=compute_ordinal_score(frame.iloc[:140].copy(),"ordinal_extreme_8")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:140],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fourth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_ordinal_validation_plan(eid)["mission_id"],"MIS-0004")
if __name__=="__main__":unittest.main()
