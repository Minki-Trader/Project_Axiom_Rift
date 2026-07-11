from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.cyclical_phase_discovery import compute_cyclical_score,cyclical_configurations,executable_configuration_map
from axiom_rift.research.cyclical_phase_study import build_cyclical_validation_plan
class CyclicalPhaseTests(unittest.TestCase):
    def test_surface_has_six_unique_executables(self)->None:
        self.assertEqual(len(cyclical_configurations()),6);self.assertEqual(len(executable_configuration_map()),6)
    def test_phase_forecast_is_prefix_invariant(self)->None:
        rows=200;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000.0*np.exp(np.cumsum(0.001*np.sin(2*np.pi*np.arange(rows)/24)));frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1.0,"low":close-1.0,"close":close});full=compute_cyclical_score(frame,"phase_24");prefix=compute_cyclical_score(frame.iloc[:160].copy(),"phase_24")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:160],right,rtol=0.0,atol=0.0,equal_nan=True)
    def test_plan_is_successor_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_cyclical_validation_plan(eid)["mission_id"],"MIS-0002")
if __name__=="__main__":unittest.main()
