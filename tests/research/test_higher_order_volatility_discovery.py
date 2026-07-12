from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.higher_order_volatility_discovery import compute_higher_volatility_score,executable_configuration_map,higher_volatility_configurations
from axiom_rift.research.higher_order_volatility_study import build_higher_volatility_validation_plan
class HigherOrderVolatilityTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(higher_volatility_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_feature_is_prefix_invariant(self)->None:
        rows=2400;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum((1+0.5*np.sin(np.arange(rows)/211))*np.sin(np.arange(rows)/17)+0.02);frame=pd.DataFrame({"time":time,"close":close});full=compute_higher_volatility_score(frame,"leverage_interaction_96_576");prefix=compute_higher_volatility_score(frame.iloc[:2200].copy(),"leverage_interaction_96_576")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:2200],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fifth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_higher_volatility_validation_plan(eid)["mission_id"],"MIS-0005")
if __name__=="__main__":unittest.main()
