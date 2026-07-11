from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.gap_recovery_discovery import compute_gap_score,executable_configuration_map,gap_configurations
from axiom_rift.research.gap_recovery_study import build_gap_validation_plan
class GapRecoveryTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(gap_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_gap_is_prefix_invariant(self)->None:
        rows=200;time=pd.date_range("2025-01-01",periods=rows,freq="5min").to_series().reset_index(drop=True);time.iloc[100:]+=pd.Timedelta(hours=2);close=20_000+np.cumsum(np.sin(np.arange(rows)/7));frame=pd.DataFrame({"time":time,"open":close-.2,"high":close+1,"low":close-1,"close":close});full=compute_gap_score(frame,"open_gap_30m");prefix=compute_gap_score(frame.iloc[:160].copy(),"open_gap_30m")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:160],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fourth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_gap_validation_plan(eid)["mission_id"],"MIS-0004")
if __name__=="__main__":unittest.main()
