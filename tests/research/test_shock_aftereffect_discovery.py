from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.shock_aftereffect_discovery import compute_shock_score,executable_configuration_map,shock_configurations
from axiom_rift.research.shock_aftereffect_study import build_shock_validation_plan
class ShockAftereffectDiscoveryTests(unittest.TestCase):
    def test_surface_has_twelve_unique_executables(self)->None:
        self.assertEqual(len(shock_configurations()),12);self.assertEqual(len(executable_configuration_map()),12)
    def test_lagged_volatility_score_is_prefix_invariant(self)->None:
        rows=190;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000.0*np.exp(np.cumsum(0.0001+0.001*np.sin(np.arange(rows)/7.0)));frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1.0,"low":close-1.0,"close":close});full=compute_shock_score(frame,"symmetric");prefix=compute_shock_score(frame.iloc[:150].copy(),"symmetric")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:150],right,rtol=0.0,atol=0.0,equal_nan=True)
    def test_plan_is_successor_bound(self)->None:
        eid=next(iter(executable_configuration_map()));plan=build_shock_validation_plan(eid);self.assertEqual(plan["mission_id"],"MIS-0002");self.assertFalse(plan["candidate_eligible_on_pass"])
if __name__=="__main__":unittest.main()
