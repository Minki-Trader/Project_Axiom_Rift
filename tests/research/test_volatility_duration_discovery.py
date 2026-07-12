from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.volatility_duration_discovery import compute_volatility_duration_score,executable_configuration_map,volatility_duration_configurations
from axiom_rift.research.volatility_duration_study import build_volatility_duration_validation_plan
class VolatilityDurationTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(volatility_duration_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_features_are_prefix_invariant(self)->None:
        rows=900;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum(np.sin(np.arange(rows)/13)+np.sin(np.arange(rows)/71));frame=pd.DataFrame({"time":time,"close":close});full=compute_volatility_duration_score(frame,"volatility_duration_96_576");prefix=compute_volatility_duration_score(frame.iloc[:820].copy(),"volatility_duration_96_576")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:820],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fourth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_volatility_duration_validation_plan(eid)["mission_id"],"MIS-0004")
if __name__=="__main__":unittest.main()
