from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.gap_recovery_discovery import DiscoveryBoundaryError,calibrate_selector,causal_gap_effective_spread,compute_gap_score,executable_configuration_map,gap_configurations
from axiom_rift.research.gap_recovery_study import build_gap_validation_plan
class GapRecoveryTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(gap_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_gap_is_prefix_invariant(self)->None:
        rows=200;time=pd.date_range("2025-01-01",periods=rows,freq="5min").to_series().reset_index(drop=True);time.iloc[100:]+=pd.Timedelta(hours=2);close=20_000+np.cumsum(np.sin(np.arange(rows)/7));frame=pd.DataFrame({"time":time,"open":close-.2,"high":close+1,"low":close-1,"close":close});full=compute_gap_score(frame,"residual_gap_after_first_bar");prefix=compute_gap_score(frame.iloc[:160].copy(),"residual_gap_after_first_bar")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:160],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fourth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_gap_validation_plan(eid)["mission_id"],"MIS-0004")
    def test_selector_uses_observed_density_boundary(self)->None:
        score=np.arange(350,dtype=float);mask=np.ones(350,dtype=bool);self.assertEqual(calibrate_selector(score,mask),245.0)
        with self.assertRaises(DiscoveryBoundaryError):calibrate_selector(score[:-1],mask[:-1])
    def test_gap_spread_repairs_only_from_past_segment_values(self)->None:
        spread=np.array([100,0,50,0,0,80,0],dtype=float);time=np.array([0,300,600,900,1800,2100,2400],dtype=np.int64)*1_000_000_000
        actual=causal_gap_effective_spread(spread,time);np.testing.assert_allclose(actual[:4],[100,100,50,75]);self.assertTrue(np.isnan(actual[4]));np.testing.assert_allclose(actual[5:],[80,80])
if __name__=="__main__":unittest.main()
