from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.nonlinear_interaction_discovery import compute_nonlinear_score,executable_configuration_map,nonlinear_configurations
from axiom_rift.research.nonlinear_interaction_study import build_nonlinear_validation_plan
class NonlinearInteractionDiscoveryTests(unittest.TestCase):
    def test_surface_has_twelve_unique_executables(self)->None:
        self.assertEqual(len(nonlinear_configurations()),12);self.assertEqual(len(executable_configuration_map()),12)
    def test_interaction_is_prefix_invariant(self)->None:
        rows=200;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000.0*np.exp(np.cumsum(0.0001+0.001*np.sin(np.arange(rows)/6.0)));frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1.0,"low":close-1.0,"close":close});full=compute_nonlinear_score(frame,"product");prefix=compute_nonlinear_score(frame.iloc[:160].copy(),"product")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:160],right,rtol=0.0,atol=0.0,equal_nan=True)
    def test_plan_is_successor_bound(self)->None:
        eid=next(iter(executable_configuration_map()));plan=build_nonlinear_validation_plan(eid);self.assertEqual(plan["mission_id"],"MIS-0002");self.assertFalse(plan["candidate_eligible_on_pass"])
if __name__=="__main__":unittest.main()
