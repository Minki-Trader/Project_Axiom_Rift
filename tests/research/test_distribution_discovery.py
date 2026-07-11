from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.distribution_discovery import compute_distribution_score,distribution_configurations,executable_configuration_map
from axiom_rift.research.distribution_study import build_distribution_validation_plan
class DistributionDiscoveryTests(unittest.TestCase):
    def test_surface_has_twelve_unique_executables(self)->None:
        self.assertEqual(len(distribution_configurations()),12);self.assertEqual(len(executable_configuration_map()),12)
    def test_skew_is_prefix_invariant(self)->None:
        rows=400;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000.0*np.exp(np.cumsum(0.001*np.sin(2*np.pi*np.arange(rows)/29)));frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1.0,"low":close-1.0,"close":close});full=compute_distribution_score(frame,"skew_96");prefix=compute_distribution_score(frame.iloc[:320].copy(),"skew_96")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:320],right,rtol=0.0,atol=0.0,equal_nan=True)
    def test_plan_is_third_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_distribution_validation_plan(eid)["mission_id"],"MIS-0003")
if __name__=="__main__":unittest.main()
