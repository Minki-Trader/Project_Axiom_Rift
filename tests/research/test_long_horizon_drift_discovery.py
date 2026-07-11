from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.long_horizon_drift_discovery import compute_long_drift_score,executable_configuration_map,long_drift_configurations
from axiom_rift.research.long_horizon_drift_study import build_long_drift_validation_plan
class LongHorizonDriftTests(unittest.TestCase):
    def test_surface_has_six_unique_executables(self)->None:self.assertEqual(len(long_drift_configurations()),6);self.assertEqual(len(executable_configuration_map()),6)
    def test_drift_is_prefix_invariant(self)->None:
        rows=420;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000*np.exp(np.cumsum(.0001+0.001*np.sin(np.arange(rows)/17)));frame=pd.DataFrame({"time":time,"open":close-.2,"high":close+1,"low":close-1,"close":close});full=compute_long_drift_score(frame,"acceleration_48_192");prefix=compute_long_drift_score(frame.iloc[:350].copy(),"acceleration_48_192")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:350],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_third_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_long_drift_validation_plan(eid)["mission_id"],"MIS-0003")
if __name__=="__main__":unittest.main()
